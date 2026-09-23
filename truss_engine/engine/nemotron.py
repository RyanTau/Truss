"""Local NeMo-Speech.cpp realtime ASR transport (not the OpenAI protocol)."""
import asyncio
from urllib.parse import urlsplit

import aiohttp

from .names import device_names

PREFIX = "conversation.item.input_audio_transcription."


class Nemotron:
    def __init__(self, options):
        self.url = options.get("nemotron_url", "http://127.0.0.1:10351").rstrip("/")
        parsed = urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            raise ValueError("nemotron_url must be an HTTP(S) server origin")
        token = options.get("nemotron_token", "")
        self.headers = {"Authorization": "Bearer " + token} if token else {}

    async def ready(self):
        async with aiohttp.ClientSession(headers=self.headers, timeout=aiohttp.ClientTimeout(total=5)) as client:
            async with client.get(self.url + "/ready", allow_redirects=False) as response:
                if response.status != 200 or (await response.json()).get("ready") is not True:
                    raise ValueError("Nemotron runtime is not ready")

    async def transcribe(self, ws, decisions, language):
        url = self.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        async with aiohttp.ClientSession(headers=self.headers) as client:
            async with client.ws_connect(url + "/v1/audio/transcriptions/realtime", heartbeat=15, max_msg_size=65536, timeout=aiohttp.ClientWSTimeout(ws_close=5)) as upstream:
                created = await asyncio.wait_for(upstream.receive_json(), 10)
                if created.get("type") != "session.created":
                    raise ValueError("Expected Nemotron transcription session")
                phrases = list(dict.fromkeys(name for c in decisions.candidates for name in device_names(c)))
                await upstream.send_json({"type": "session.update", "session": {
                    "sample_rate": 16000, "language": language,
                    "automatic_punctuation": False, "verbatim": True,
                    "speech_contexts": [{"phrases": phrases, "boost": 3.0}],
                }})
                updated = await asyncio.wait_for(upstream.receive_json(), 10)
                if updated.get("type") != "session.updated":
                    raise ValueError("Nemotron rejected transcription settings")
                ended = False

                async def send():
                    nonlocal ended
                    pending = bytearray()
                    total = 0
                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.BINARY:
                            total += len(message.data)
                            if total > 1_920_000:
                                raise ValueError("Maximum audio duration is 60 seconds")
                            pending.extend(message.data)
                            # Coalesce tiny/odd packets into 80 ms aligned PCM16.
                            while len(pending) >= 2560:
                                await upstream.send_bytes(bytes(pending[:2560]))
                                del pending[:2560]
                        elif message.type == aiohttp.WSMsgType.TEXT and message.json().get("type") == "end":
                            if len(pending) % 2:
                                raise ValueError("PCM16 stream ended on a partial sample")
                            if pending:
                                await upstream.send_bytes(bytes(pending))
                            ended = True
                            await upstream.send_json({"type": "input_audio_buffer.commit"})
                            return
                        else:
                            raise ValueError("Unexpected audio message")
                    raise ValueError("Audio socket disconnected")

                async def receive():
                    finals = []
                    partial = ""
                    completed_after_end = False
                    async for message in upstream:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            raise ValueError("Invalid Nemotron event")
                        event = message.json()
                        kind = event.get("type")
                        if kind in (PREFIX + "delta", PREFIX + "completed"):
                            value = event.get("delta" if kind.endswith(".delta") else "transcript")
                            if not isinstance(value, str):
                                raise ValueError("Invalid Nemotron transcript")
                            if kind.endswith(".delta"):
                                partial += value
                            else:
                                finals.append(value)
                                partial = ""
                                completed_after_end = ended
                            await decisions.update(" ".join([*finals, partial]).strip())
                        elif kind == "input_audio_buffer.committed":
                            if not ended or not completed_after_end:
                                raise ValueError("Nemotron committed without final transcription")
                            return
                        else:
                            raise ValueError("Unexpected Nemotron event")
                    raise ValueError("Nemotron disconnected before commit")

                sender, receiver = asyncio.create_task(send()), asyncio.create_task(receive())
                try:
                    done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        await task
                    await sender
                    await asyncio.wait_for(receiver, 15)
                finally:
                    for task in (sender, receiver):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sender, receiver, return_exceptions=True)
