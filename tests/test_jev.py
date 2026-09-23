"""Offline Jev API-contract and streaming tests; no paid calls or HA devices."""
import asyncio
import builtins
import copy
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import support
from engine.jev import JevClient
from engine.models import LocalModels
from engine.server import create_app
from test_engine import FakeModels, TOKEN, HEADERS
from run import decision_options

CANDIDATES = [{"id": "light.kitchen:on", "entity_id": "light.kitchen", "label": "Turn on Kitchen",
               "name": "Kitchen", "aliases": ["Kitchen lamp"], "area": "Kitchen",
               "tool": "HassTurnOn", "arguments": {"name": "light.kitchen"}}]


class JevTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.status = 200
        self.payload = {"model": "jev-test", "answers": {"action": {
            "type": "choice", "choice": "action_0", "confidence": .9,
            "probabilities": {"wait": .01, "action_0": .99}}}}
        async def endpoint(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer fake-typesafe-key")
            self.requests.append(await request.json())
            return web.json_response(self.payload, status=self.status)
        app = web.Application()
        app.router.add_post("/v1/systemone", endpoint)
        self.provider = TestServer(app)
        await self.provider.start_server()
        self.endpoint_patch = patch("engine.jev.ENDPOINT", str(self.provider.make_url("/v1/systemone")))
        self.endpoint_patch.start()
        self.options = {"decision_backend": "jev", "typesafe_api_key": "fake-typesafe-key", "jev_model": "jev-latest", "api_token": TOKEN}
        self.client = JevClient(self.options)
        await self.client.start()

    async def asyncTearDown(self):
        await self.client.close()
        self.endpoint_patch.stop()
        await self.provider.close()

    async def test_contract_and_raw_scores(self):
        scores = await self.client.score("Turn on", CANDIDATES)
        self.assertEqual(scores, {"light.kitchen:on": .99})
        request = self.requests[0]
        self.assertEqual(request["state"], {"transcript": "Turn on"})
        self.assertEqual(request["model"], "jev-latest")
        self.assertEqual(request["questions"]["action"]["criteria"]["action_0"]["aliases"], ["Kitchen lamp"])
        self.assertNotIn("api_token", str(request))
        self.assertNotIn("HassTurnOn", str(request))

    async def test_malformed_responses_fail_closed(self):
        original = copy.deepcopy(self.payload)
        bad_answers = [
            {"probabilities": {"wait": .01}},
            {"probabilities": {"wait": .01, "action_0": float("nan")}},
            {"probabilities": {"wait": .01, "action_0": True}},
            {"probabilities": {"wait": .9, "action_0": .9}},
            {"probabilities": {"wait": .01, "action_0": .98, "invented": .01}},
            {"choice": "wait"}, {"choice": "invented"}, {"confidence": 2}, {"type": "noul"},
        ]
        for changes in bad_answers:
            self.payload = copy.deepcopy(original)
            self.payload["answers"]["action"].update(changes)
            with self.assertRaisesRegex(ValueError, "Invalid Jev"):
                await self.client.score("Turn", CANDIDATES)

    async def test_provider_errors_are_not_retried_or_replaced_with_laya(self):
        for status in (401, 429, 503, 302):
            self.status = status
            before = len(self.requests)
            with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                await self.client.score("Turn", CANDIDATES)
            self.assertEqual(len(self.requests), before + 1)

    async def test_text_engine_works_without_laya_or_torch(self):
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] in ("laya", "torch", "transformers", "huggingface_hub", "sherpa_onnx"):
                raise AssertionError("Unexpected local model import: " + name)
            return original_import(name, *args, **kwargs)
        app = create_app({**self.options, "bundled_stt": False})
        server = TestServer(app)
        try:
            with patch.object(builtins, "__import__", guarded_import):
                await server.start_server()
                await app["engine"].load_task
                self.assertTrue(app["engine"].ready)
                self.assertIsNone(app["engine"].models.agent)
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(server.make_url("/v1/stream"), headers=HEADERS) as ws:
                        await ws.send_json({"type": "start", "sample_rate": 16000, "candidates": CANDIDATES, "stt": {"mode": "text"}, "text": "Kitchen on"})
                        received = []
                        while True:
                            event = await asyncio.wait_for(ws.receive_json(), 3)
                            received.append(event)
                            if event["type"] == "done":
                                break
                            self.assertNotEqual(event["type"], "error")
                    score = next(e for e in received if e["type"] == "probabilities")
                    self.assertEqual(score["decision_backend"], "jev")
                    self.assertEqual(score["probabilities"], {"light.kitchen:on": .99})
        finally:
            await server.close()

    async def test_voice_scores_arrive_before_audio_ends(self):
        models = FakeModels()
        models.score = lambda *args: self.fail("Jev must never call local Laya scoring")
        app = create_app(self.options, models=models)
        server = TestServer(app)
        await server.start_server()
        await app["engine"].load_task
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(server.make_url("/health"), headers=HEADERS) as response:
                    health = await response.json()
                    self.assertEqual(health["decision_backend"], "jev")
                    self.assertNotIn("fake-typesafe-key", str(health))
                async with session.ws_connect(server.make_url("/v1/stream"), headers=HEADERS) as ws:
                    await ws.send_json({"type": "start", "sample_rate": 16000, "candidates": CANDIDATES, "stt": {"mode": "bundled"}})
                    await ws.send_bytes(bytes(2560))
                    await asyncio.wait_for(ws.receive_json(), 3)  # partial
                    score = await asyncio.wait_for(ws.receive_json(), 3)
                    self.assertEqual(score["type"], "probabilities")
                    self.assertEqual(score["decision_backend"], "jev")
                    await ws.send_json({"type": "end"})
                    self.assertEqual((await ws.receive_json())["type"], "done")
        finally:
            await server.close()

    async def test_missing_key_and_unknown_backend_rejected(self):
        with self.assertRaises(ValueError):
            create_app({"api_token": TOKEN, "decision_backend": "jev"})
        with self.assertRaises(ValueError):
            create_app({"api_token": TOKEN, "decision_backend": "unknown"})

    async def test_invalid_remote_scores_end_session_without_probability_event(self):
        self.payload["answers"]["action"]["probabilities"] = {"action_0": .99}
        app = create_app(self.options, models=FakeModels())
        server = TestServer(app)
        await server.start_server()
        await app["engine"].load_task
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(server.make_url("/v1/stream"), headers=HEADERS) as ws:
                    await ws.send_json({"type": "start", "sample_rate": 16000, "candidates": CANDIDATES, "stt": {"mode": "text"}, "text": "Kitchen on"})
                    self.assertEqual((await ws.receive_json())["type"], "partial")
                    self.assertEqual((await asyncio.wait_for(ws.receive_json(), 3))["type"], "error")
        finally:
            await server.close()

    async def test_backend_environment_overrides(self):
        result = decision_options({"decision_backend": "laya", "threads": 4}, {
            "TRUSS_DECISION_BACKEND": "jev", "TYPESAFE_API_KEY": "key", "TYPESAFE_MODEL": "jev-test"})
        self.assertEqual(result, {"decision_backend": "jev", "threads": 4, "typesafe_api_key": "key", "jev_model": "jev-test"})
