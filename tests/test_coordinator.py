"""Exercise the real audio bridge and MCP client with HA/model test doubles."""
import asyncio
from contextlib import nullcontext
import json
import sys
import types
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from support import integration
from engine.server import create_app
from engine.streaming import LiveDecisions
from test_engine import FakeModels, TOKEN


def load_coordinator():
    # HA cannot run under the workspace's Python 3.9. Stub only its registry,
    # event and HTTP-session access; actual Truss transports run below.
    modules = {}
    for name in ("homeassistant", "homeassistant.components", "homeassistant.components.homeassistant", "homeassistant.components.homeassistant.exposed_entities", "homeassistant.helpers", "homeassistant.helpers.area_registry", "homeassistant.helpers.device_registry", "homeassistant.helpers.entity_registry", "homeassistant.helpers.aiohttp_client"):
        modules[name] = types.ModuleType(name)
    modules["homeassistant.components.homeassistant.exposed_entities"].async_should_expose = lambda hass, assistant, entity_id: entity_id in hass.exposed
    for kind in ("area", "device", "entity"):
        module = modules[f"homeassistant.helpers.{kind}_registry"]
        module.async_get = lambda hass: types.SimpleNamespace(async_get=lambda entity_id: None, async_get_area=lambda area_id: None)
        setattr(modules["homeassistant.helpers"], kind + "_registry", module)
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = lambda hass: hass.session
    with patch.dict(sys.modules, modules):
        return integration("coordinator")


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine_app = create_app({"api_token": TOKEN}, models=FakeModels())
        self.engine = TestServer(self.engine_app)
        await self.engine.start_server()
        await self.engine_app["engine"].load_task
        self.calls = []
        self.action_received = asyncio.Event()
        self.fail_action = False
        self.events = []

        async def mcp_endpoint(request):
            self.assertEqual(request.headers["Authorization"], "Bearer ha-secret")
            message = await request.json()
            if "id" not in message:
                return web.Response(status=202)
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": "2025-03-26"}
            elif method == "tools/list":
                result = {"tools": [{"name": "homeassistant__HassTurnOn", "inputSchema": {"properties": {"name": {"type": "string"}}}}]}
            else:
                self.calls.append(message["params"])
                self.action_received.set()
                result = {"isError": self.fail_action, "content": [{"type": "text", "text": '{"response_type":"action_done"}'}]}
            return web.json_response({"jsonrpc": "2.0", "id": message["id"], "result": result})

        mcp_app = web.Application()
        mcp_app.router.add_post("/api/mcp", mcp_endpoint)
        self.mcp_server = TestServer(mcp_app)
        await self.mcp_server.start_server()
        self.session = aiohttp.ClientSession()
        state = types.SimpleNamespace(name="Kitchen", state="off")
        self.hass = types.SimpleNamespace(session=self.session, exposed={"light.kitchen"}, states=types.SimpleNamespace(get=lambda entity_id: state), bus=types.SimpleNamespace(async_fire=lambda name, data: self.events.append((name, data))))
        entry = types.SimpleNamespace(options={}, data={"mcp_url": str(self.mcp_server.make_url("/api/mcp")), "mcp_token": "ha-secret", "engine_url": str(self.engine.make_url("/")).rstrip("/"), "engine_token": TOKEN, "entities": ["light.kitchen"], "threshold": .95, "margin": .05, "stt_mode": "bundled"})
        self.coordinator = load_coordinator().TrussCoordinator(self.hass, entry)
        await self.coordinator.async_connect()
        if not hasattr(asyncio, "timeout"):
            from async_timeout import timeout
            self.timeout_patch = patch.object(asyncio, "timeout", timeout, create=True)
        else:
            self.timeout_patch = nullcontext()
        self.timeout_patch.__enter__()

    async def asyncTearDown(self):
        self.timeout_patch.__exit__(None, None, None)
        await self.coordinator.async_close()
        await self.session.close()
        await self.engine.close()
        await self.mcp_server.close()

    async def audio_until_action(self):
        yield bytes(2560)
        # This cannot finish until MCP execution has happened DURING speech.
        await asyncio.wait_for(self.action_received.wait(), 3)
        yield bytes(2560)

    async def test_action_before_audio_end_and_single_use_receipt(self):
        receipt = await asyncio.wait_for(self.coordinator.async_stream(self.audio_until_action(), "en"), 5)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0], {"name": "homeassistant__HassTurnOn", "arguments": {"name": "light.kitchen"}})
        self.assertTrue(self.coordinator.consume_receipt(receipt).startswith("Requested:"))
        self.assertIsNone(self.coordinator.consume_receipt(receipt))
        self.assertTrue(any(name == "truss_probabilities" for name, _ in self.events))
        self.assertEqual([data["status"] for name, data in self.events if name == "truss_action"], ["accepted"])

    async def test_failed_action_not_retried_on_final_transcript(self):
        self.fail_action = True
        receipt = await self.coordinator.async_stream(self.audio_until_action(), "en")
        self.assertEqual(len(self.calls), 1)
        self.assertIn("not been retried", self.coordinator.consume_receipt(receipt))

    async def test_scored_prefix_can_execute_while_more_words_arrive(self):
        started, release = asyncio.Event(), asyncio.Event()
        extended = asyncio.Event()
        transcripts = []

        class TrackedDecisions(LiveDecisions):
            async def update(self, text):
                await super().update(text)
                if text.endswith("please"):
                    extended.set()

        def transcribe(*args):
            text = "turn on kitchen" if not transcripts else "turn on kitchen please"
            transcripts.append(text)
            return text

        async def score(text, candidates):
            if text == "turn on kitchen":
                started.set()
                await release.wait()
            return {c["id"]: .99 for c in candidates}

        engine = self.engine_app["engine"]
        engine.models.transcribe = transcribe
        engine.score = score

        async def audio():
            yield bytes(2560)
            await started.wait()
            yield bytes(2560)
            await extended.wait()
            release.set()
            await self.action_received.wait()

        with patch("engine.server.LiveDecisions", TrackedDecisions):
            await asyncio.wait_for(self.coordinator.async_stream(audio(), "en"), 5)
        self.assertEqual(len(self.calls), 1)
        probabilities = [event for name, event in self.events if name == "truss_probabilities"]
        self.assertTrue(any(e["revision"] == 1 and e["current_revision"] == 2 for e in probabilities))

    async def test_unexposed_entity_never_enters_session(self):
        self.hass.exposed.clear()
        with self.assertRaises(ValueError):
            await self.coordinator.async_stream(self.audio_until_action(), "en")
        self.assertEqual(self.calls, [])

    async def test_receipts_do_not_cross_sessions(self):
        first = await self.coordinator.async_stream(self.audio_until_action(), "en")
        second = await self.coordinator.async_stream(self.audio_until_action(), "en")
        self.assertNotEqual(first, second)
        self.assertIsNotNone(self.coordinator.consume_receipt(first))
        self.assertIsNotNone(self.coordinator.consume_receipt(second))
