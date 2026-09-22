"""Authenticated streaming engine. Never receives Home Assistant credentials."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hmac
import logging
import struct
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
from .models import LocalModels
from .streaming import LiveDecisions
from . import VERSION, SCORE_SCOPE

LOGGER = logging.getLogger(__name__)


def validate_start(start):
    if not isinstance(start, dict) or start.get("type") != "start" or start.get("sample_rate") != 16000:
        raise ValueError("Expected start message with 16000 Hz mono PCM16 audio")
    candidates = start.get("candidates", [])
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 48:
        raise ValueError("Expected 1-48 action candidates")
    ids = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("Invalid candidate")
        for key in ("id", "label", "entity_id"):
            if not isinstance(item.get(key), str) or not item[key] or len(item[key]) > 160:
                raise ValueError("Invalid candidate field")
        if item["id"] in ids:
            raise ValueError("Duplicate candidate ID")
        ids.add(item["id"])
        if not isinstance(item.get("area", ""), str) or len(item.get("area", "")) > 120:
            raise ValueError("Invalid area")
        aliases = item.get("aliases", [])
        if not isinstance(item.get("name", ""), str) or len(item.get("name", "")) > 160:
            raise ValueError("Invalid device name")
        if not isinstance(aliases, list) or len(aliases) > 8 or any(not isinstance(a, str) or len(a) > 120 for a in aliases):
            raise ValueError("Invalid aliases")
    stt = start.get("stt", {})
    if not isinstance(stt, dict) or stt.get("mode") not in ("bundled", "external", "sherpa"):
        raise ValueError("Unknown transcription mode")
    if stt["mode"] != "bundled":
        url = urlsplit(stt.get("url", ""))
        if url.scheme not in ("ws", "wss") or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("Invalid external transcription URL")
    return candidates


class Engine:
    def __init__(self, options, models=None):
        self.options = options
        self.models = models or LocalModels(options)
        self.inference_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="laya")
        self.audio_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sherpa")
        self.ready = False
        self.error = None
        self.active = 0
        self.sockets = set()
        self.load_task = None

    async def startup(self, app):
        self.load_task = asyncio.create_task(self.load())

    async def load(self):
        try:
            await asyncio.get_running_loop().run_in_executor(self.inference_pool, self.models.load)
            self.ready = True
            LOGGER.info("Truss models are ready")
        except Exception as error:
            self.error = type(error).__name__
            LOGGER.error("Model startup failed (%s). Check model cache, network, and memory.", self.error)

    async def cleanup(self, app):
        for ws in list(self.sockets):
            await ws.close(code=1001, message=b"Engine stopping")
        if self.load_task:
            await asyncio.gather(self.load_task, return_exceptions=True)
        self.inference_pool.shutdown(wait=False, cancel_futures=True)
        self.audio_pool.shutdown(wait=False, cancel_futures=True)

    async def health(self, request):
        return web.json_response({"protocol": "truss-v1", "engine_version": VERSION, "score_scope": SCORE_SCOPE, "ready": self.ready, "bundled_stt": self.models.recognizer is not None, "error": self.error, "active_sessions": self.active})

    async def score(self, text, candidates):
        return await asyncio.get_running_loop().run_in_executor(self.inference_pool, self.models.score, text, candidates)

    async def audio(self, stream, pcm, final=False):
        return await asyncio.get_running_loop().run_in_executor(self.audio_pool, self.models.transcribe, stream, pcm, final)

    async def stream(self, request):
        if not self.ready:
            raise web.HTTPServiceUnavailable(text="Models are still loading or failed")
        if self.active >= 2:
            raise web.HTTPTooManyRequests(text="Two voice sessions are already active")
        self.active += 1
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=65536)
        decisions_task = reader_task = None
        try:
            await ws.prepare(request)
            self.sockets.add(ws)
            start = await asyncio.wait_for(ws.receive_json(), timeout=10)
            candidates = validate_start(start)
            async def emit(event):
                if event.get("type") == "probabilities":
                    event["score_scope"] = SCORE_SCOPE
                await ws.send_json(event)
            decisions = LiveDecisions(self.score, emit, candidates)
            decisions_task = asyncio.create_task(decisions.run())
            if start["stt"]["mode"] == "bundled":
                reader_task = asyncio.create_task(self.bundled(ws, decisions))
            else:
                reader_task = asyncio.create_task(self.external(ws, decisions, start))

            async def run_session():
                done, _ = await asyncio.wait([reader_task, decisions_task], return_when=asyncio.FIRST_COMPLETED)
                # Inference errors must interrupt audio reception immediately.
                if decisions_task in done:
                    await decisions_task
                await reader_task
                decisions.finish()
                await decisions_task
                await ws.send_json({"type": "done", "text": decisions.text, "revision": decisions.revision})

            await asyncio.wait_for(run_session(), timeout=75)
        except (Exception,) as error:
            LOGGER.warning("Voice session failed (%s)", type(error).__name__)
            if ws.prepared and not ws.closed:
                await ws.send_json({"type": "error", "message": "Transcription or inference failed; check endpoint compatibility, models, and session limits."})
        finally:
            # Release bookkeeping before cancellable disconnect cleanup.
            self.sockets.discard(ws)
            self.active -= 1
            for task in (reader_task, decisions_task):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (reader_task, decisions_task) if t), return_exceptions=True)
            if ws.prepared:
                await ws.close()
        return ws

    async def bundled(self, ws, decisions):
        stream = await asyncio.get_running_loop().run_in_executor(self.audio_pool, self.models.create_stream, decisions.candidates)
        pending = bytearray()
        total = 0
        async for message in ws:
            if message.type == aiohttp.WSMsgType.BINARY:
                total += len(message.data)
                if total > 1_920_000:
                    raise ValueError("Maximum audio duration is 60 seconds")
                pending.extend(message.data)
                # 80 ms batches avoid overhead from tiny satellite packets.
                while len(pending) >= 2560:
                    frame = bytes(pending[:2560])
                    del pending[:2560]
                    await decisions.update(await self.audio(stream, frame))
            elif message.type == aiohttp.WSMsgType.TEXT and message.json().get("type") == "end":
                if len(pending) % 2:
                    raise ValueError("PCM16 stream ended on a partial sample")
                await decisions.update(await self.audio(stream, bytes(pending), True))
                return
            else:
                raise ValueError("Unexpected audio message")
        raise ValueError("Audio socket disconnected")

    async def external(self, ws, decisions, start):
        settings = start["stt"]
        sherpa = settings["mode"] == "sherpa"
        headers = {"Authorization": "Bearer " + settings["token"]} if settings.get("token") else {}
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(settings["url"], headers=headers, heartbeat=15, max_msg_size=65536) as upstream:
                if not sherpa:
                    await upstream.send_json({"type": "start", "sample_rate": 16000, "format": "pcm_s16le", "channels": 1, "language": start.get("language", "en")})
                ended = False

                async def send():
                    nonlocal ended
                    total = 0
                    pending = b""
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.BINARY:
                            total += len(message.data)
                            if total > 1_920_000:
                                raise ValueError("Maximum audio duration is 60 seconds")
                            if sherpa:
                                pending += message.data
                                size = len(pending) // 2 * 2
                                if size:
                                    values = [v[0] / 32768.0 for v in struct.iter_unpack("<h", pending[:size])]
                                    await upstream.send_bytes(struct.pack(f"<{len(values)}f", *values))
                                    pending = pending[size:]
                            else:
                                await upstream.send_bytes(message.data)
                        elif message.type == aiohttp.WSMsgType.TEXT and message.json().get("type") == "end":
                            if total % 2:
                                raise ValueError("PCM16 stream ended on a partial sample")
                            ended = True
                            if sherpa:
                                await upstream.send_str("Done")
                            else:
                                await upstream.send_json({"type": "end"})
                            return
                        else:
                            raise ValueError("Unexpected audio message")
                    raise ValueError("Audio socket disconnected")

                async def receive():
                    segments = []
                    received_after_end = False
                    async for message in upstream:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            raise ValueError("External transcript must be JSON text")
                        if sherpa and message.data == "Done!":
                            if not ended or not received_after_end:
                                raise ValueError("Sherpa finished without a final transcript")
                            return
                        event = message.json()
                        if sherpa:
                            segment = event.get("segment")
                            text = event.get("text")
                            if type(segment) is not int or not isinstance(text, str) or not 0 <= segment <= len(segments) or segment < len(segments) - 1 or segment > 120:
                                raise ValueError("Invalid sherpa transcript segment")
                            if segment == len(segments):
                                segments.append(text)
                            else:
                                segments[segment] = text
                            await decisions.update(" ".join(segments).strip())
                            received_after_end = received_after_end or ended
                            continue
                        if event.get("type") in ("partial", "final"):
                            await decisions.update(event["text"])
                            if event["type"] == "final":
                                if not ended:
                                    raise ValueError("Provider finalized before audio ended; use full-utterance partials")
                                return
                        elif event.get("type") == "error":
                            raise ValueError("External STT reported an error")
                    # The upstream Python server closes normally after its final
                    # segment; the C++ server sends Done! instead.
                    if sherpa and ended and received_after_end and upstream.close_code == 1000:
                        return
                    raise ValueError("External STT disconnected before final transcript")

                sender, receiver = asyncio.create_task(send()), asyncio.create_task(receive())
                try:
                    done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        await task
                    await sender
                    await asyncio.wait_for(receiver, timeout=15)
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)


def create_app(options, models=None):
    token = options.get("api_token", "")
    if not isinstance(token, str) or len(token) < 24:
        raise ValueError("Set api_token to a random secret of at least 24 characters")

    @web.middleware
    async def authenticate(request, handler):
        expected = "Bearer " + token
        if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
            raise web.HTTPUnauthorized()
        return await handler(request)

    engine = Engine(options, models)
    app = web.Application(middlewares=[authenticate], client_max_size=65536)
    app["engine"] = engine
    app.router.add_get("/health", engine.health)
    app.router.add_get("/v1/stream", engine.stream)
    app.on_startup.append(engine.startup)
    app.on_cleanup.append(engine.cleanup)
    return app
