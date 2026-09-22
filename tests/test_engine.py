import asyncio
import struct
import unittest
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from support import integration
from engine.server import create_app

TOKEN = "test-secret-at-least-24-characters"
HEADERS = {"Authorization": "Bearer " + TOKEN}


class FakeModels:
    recognizer = object()

    def load(self):
        pass

    def create_stream(self, candidates=None):
        return {}

    def transcribe(self, stream, pcm, final=False):
        return "turn on kitchen"

    def score(self, text, candidates):
        return {c["id"]: .99 for c in candidates}


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app({"api_token": TOKEN}, models=FakeModels())
        self.server = TestServer(self.app)
        await self.server.start_server()
        await self.app["engine"].load_task
        self.client = aiohttp.ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    def start(self, stt=None):
        return {"type": "start", "sample_rate": 16000, "language": "en", "candidates": [{"id": "light.kitchen:on", "entity_id": "light.kitchen", "label": "Turn on Kitchen"}], "stt": stt or {"mode": "bundled"}}

    async def next_type(self, ws, kind):
        for _ in range(10):
            message = await asyncio.wait_for(ws.receive_json(), 3)
            self.assertNotEqual(message["type"], "error", message)
            if message["type"] == kind:
                return message
        self.fail("Expected message " + kind)

    async def test_auth_required_for_health_and_websocket(self):
        for path in ("/health", "/v1/stream"):
            async with self.client.get(self.server.make_url(path)) as response:
                self.assertEqual(response.status, 401)

    async def test_bundled_scores_arrive_before_audio_end(self):
        async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
            await ws.send_json(self.start())
            await ws.send_bytes(bytes(2560))
            event = await self.next_type(ws, "probabilities")
            self.assertEqual(event["probabilities"], {"light.kitchen:on": .99})
            # We have deliberately NOT sent end yet. A threshold can fire now.
            gate = integration("catalog").DecisionGate(self.start()["candidates"], .95)
            self.assertIsNotNone(gate.select(event["probabilities"]))
            await ws.send_json({"type": "end"})
            self.assertEqual((await self.next_type(ws, "done"))["text"], "turn on kitchen")
            self.assertIsNone(gate.select(event["probabilities"]))

    async def test_external_partials_forwarded_while_audio_is_live(self):
        upstream_ended = asyncio.Event()

        async def external(request):
            self.assertEqual(request.headers["Authorization"], "Bearer external-token")
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            start = await ws.receive_json()
            self.assertEqual(start["format"], "pcm_s16le")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await ws.send_json({"type": "partial", "text": "turn on kitchen"})
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    upstream_ended.set()
                    await ws.send_json({"type": "final", "text": "turn on kitchen"})
                    break
            await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/stt", external)
        upstream = TestServer(app)
        await upstream.start_server()
        try:
            async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
                await ws.send_json(self.start({"mode": "external", "url": str(upstream.make_url("/stt")).replace("http:", "ws:"), "token": "external-token"}))
                await ws.send_bytes(bytes(2560))
                await self.next_type(ws, "probabilities")
                self.assertFalse(upstream_ended.is_set())
                await ws.send_json({"type": "end"})
                await self.next_type(ws, "done")
                self.assertTrue(upstream_ended.is_set())
        finally:
            await upstream.close()

    async def test_invalid_start_and_odd_final_audio_fail(self):
        async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
            await ws.send_json({"type": "start", "sample_rate": 8000})
            self.assertEqual((await ws.receive_json())["type"], "error")
        async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
            await ws.send_json(self.start())
            await ws.send_bytes(b"x")
            await ws.send_json({"type": "end"})
            self.assertEqual((await ws.receive_json())["type"], "error")

    async def test_sherpa_converts_audio_and_accumulates_live_segments(self):
        await self.check_sherpa_stream(False)

    async def test_sherpa_accepts_done_terminator(self):
        await self.check_sherpa_stream(True)

    async def check_sherpa_stream(self, terminator):
        received = bytearray()

        async def sherpa(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    received.extend(msg.data)
                    await ws.send_json({"segment": 0, "text": "turn on"})
                    await ws.send_json({"segment": 1, "text": "kitchen"})
                else:
                    self.assertEqual(msg.data, "Done")
                    await ws.send_json({"segment": 1, "text": "kitchen light"})
                    if terminator:
                        await ws.send_str("Done!")
                    break
            await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/", sherpa)
        upstream = TestServer(app)
        await upstream.start_server()
        try:
            async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
                await ws.send_json(self.start({"mode": "sherpa", "url": str(upstream.make_url("/")).replace("http:", "ws:")}))
                pcm = struct.pack("<hhh", -32768, 0, 16384)
                await ws.send_bytes(pcm[:1])
                await ws.send_bytes(pcm[1:])
                event = await self.next_type(ws, "probabilities")
                self.assertEqual(event["text"], "turn on kitchen")
                self.assertEqual(struct.unpack("<fff", received), (-1.0, 0.0, 0.5))
                await ws.send_json({"type": "end"})
                self.assertEqual((await self.next_type(ws, "done"))["text"], "turn on kitchen light")
        finally:
            await upstream.close()

    async def test_sherpa_premature_close_fails(self):
        async def sherpa(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.receive_bytes()
            await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/", sherpa)
        upstream = TestServer(app)
        await upstream.start_server()
        try:
            async with self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS) as ws:
                await ws.send_json(self.start({"mode": "sherpa", "url": str(upstream.make_url("/")).replace("http:", "ws:")}))
                await ws.send_bytes(bytes(2560))
                self.assertEqual((await asyncio.wait_for(ws.receive_json(), 3))["type"], "error")
        finally:
            await upstream.close()

    async def test_disconnect_releases_session(self):
        ws = await self.client.ws_connect(self.server.make_url("/v1/stream"), headers=HEADERS)
        await ws.send_json(self.start())
        await ws.close()
        for _ in range(20):
            if self.app["engine"].active == 0:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.app["engine"].active, 0)
