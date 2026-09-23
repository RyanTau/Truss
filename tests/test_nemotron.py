"""Exercise the native runtime wire contract through the Truss voice socket."""
import asyncio
import unittest
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from support import integration
from engine.models import LocalModels
from engine.nemotron import Nemotron, PREFIX
from engine.server import create_app
from test_engine import FakeModels, TOKEN, HEADERS


class NemotronTests(unittest.IsolatedAsyncioTestCase):
    async def check_session(self, failure=None):
        received = bytearray()
        committed = asyncio.Event()
        ready = True

        async def health(request):
            return web.json_response({"ready": ready})

        async def native(request):
            self.assertEqual(request.headers.get("Authorization"), "Bearer native-secret")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "session.created"})
            config = await ws.receive_json()
            self.assertEqual(config["session"]["sample_rate"], 16000)
            self.assertIn("Turkish lamp", config["session"]["speech_contexts"][0]["phrases"])
            await ws.send_json({"type": "session.updated"})
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    received.extend(msg.data)
                    if failure == "disconnect":
                        break
                    if failure == "provider_error":
                        await ws.send_json({"type": "error", "error": {"message": "failed"}})
                        break
                    if failure == "malformed":
                        await ws.send_json({"type": PREFIX + "delta", "delta": 12})
                        break
                    await ws.send_json({"type": PREFIX + "delta", "delta": "turn on "})
                    await ws.send_json({"type": PREFIX + "delta", "delta": "Turkish lamp"})
                else:
                    self.assertEqual(msg.json()["type"], "input_audio_buffer.commit")
                    committed.set()
                    if failure != "no_final":
                        # A final replaces the tentative segment, rather than duplicating it.
                        await ws.send_json({"type": PREFIX + "completed", "transcript": "Turn on the Turkish lamp"})
                    await ws.send_json({"type": "input_audio_buffer.committed"})
                    break
            await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/ready", health)
        app.router.add_get("/v1/audio/transcriptions/realtime", native)
        async with TestServer(app) as upstream:
            options = {"api_token": TOKEN, "stt_backend": "nemotron", "nemotron_url": str(upstream.make_url("/")), "nemotron_token": "native-secret"}
            engine_app = create_app(options, models=FakeModels())
            async with TestServer(engine_app) as server, aiohttp.ClientSession() as client:
                await engine_app["engine"].load_task
                async with client.get(server.make_url("/health"), headers=HEADERS) as response:
                    status = await response.json()
                    self.assertTrue(status["ready"])
                    self.assertTrue(status["bundled_stt"])
                    self.assertEqual(status["stt_backend"], "nemotron")
                async with client.ws_connect(server.make_url("/v1/stream"), headers=HEADERS) as ws:
                    await ws.send_json({"type": "start", "sample_rate": 16000, "stt": {"mode": "bundled"}, "candidates": [
                        {"id": "light.ball:on", "entity_id": "light.ball", "label": "Turn on Ball lamp", "aliases": ["Turkish lamp"]}
                    ]})
                    # Odd packet boundaries must not reach the native PCM decoder.
                    await ws.send_bytes(b"\x00")
                    await ws.send_bytes(bytes(2559))
                    if failure not in ("disconnect", "provider_error", "malformed"):
                        for _ in range(10):
                            event = await asyncio.wait_for(ws.receive_json(), 3)
                            self.assertNotEqual(event["type"], "error")
                            if event["type"] == "probabilities" and event["text"] == "turn on Turkish lamp":
                                break
                        else:
                            self.fail("No live score before end")
                        self.assertFalse(committed.is_set())
                        self.assertEqual(len(received), 2560)
                        if failure == "odd_pcm":
                            await ws.send_bytes(b"\x00")
                        await ws.send_json({"type": "end"})
                    for _ in range(10):
                        event = await asyncio.wait_for(ws.receive_json(), 3)
                        if event["type"] in ("done", "error"):
                            break
                    self.assertEqual(event["type"], "error" if failure else "done")
                    if not failure:
                        self.assertEqual(event["text"], "Turn on the Turkish lamp")
                ready = False
                async with client.get(server.make_url("/health"), headers=HEADERS) as response:
                    self.assertFalse((await response.json())["ready"])

    async def test_live_partials_final_replacement_and_health(self):
        await self.check_session()

    async def test_failures_do_not_succeed_or_fallback(self):
        for failure in ("disconnect", "provider_error", "malformed", "no_final", "odd_pcm"):
            with self.subTest(failure=failure):
                await self.check_session(failure)

    def test_native_mode_does_not_load_zipformer(self):
        with patch.dict("sys.modules", {"sherpa_onnx": None, "sentencepiece": None, "huggingface_hub": None}):
            model = LocalModels({"decision_backend": "jev", "stt_backend": "nemotron"})
            model.load()
            self.assertIsNone(model.recognizer)

    def test_reject_invalid_server_origins(self):
        for url in ("ws://localhost", "http://user:pass@localhost", "http://localhost/path", "http://localhost?token=x"):
            with self.assertRaises(ValueError):
                Nemotron({"nemotron_url": url})

    def test_environment_configuration(self):
        from run import decision_options
        self.assertEqual(decision_options({}, {"TRUSS_STT_BACKEND": "nemotron", "TRUSS_NEMOTRON_URL": "http://localhost:10351", "TRUSS_NEMOTRON_TOKEN": "secret"}),
                         {"stt_backend": "nemotron", "nemotron_url": "http://localhost:10351", "nemotron_token": "secret"})
