"""Bridge streamed Assist audio to Truss, executing selected actions via MCP."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

import aiohttp
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .catalog import DecisionGate, build_candidates
from .const import DOMAIN, EVENT_ACTION, EVENT_PROBABILITIES, RECEIPT_PREFIX
from .mcp import MCPClient
from .selection import selected_entity_ids

_LOGGER = logging.getLogger(__name__)


class TrussCoordinator:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.config = {**entry.data, **entry.options}
        self.session = async_get_clientsession(hass)
        self.mcp = MCPClient(self.session, self.config["mcp_url"], self.config["mcp_token"])
        self.tools = []
        self.receipts = {}
        self.websockets = set()

    async def async_connect(self):
        await self.mcp.initialize()
        self.tools = await self.mcp.list_tools()
        async with self.session.get(self.config["engine_url"] + "/health", headers=self.headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            health = await response.json()
            if health.get("protocol") != "truss-v1" or not health.get("ready"):
                raise ValueError("Truss models are not ready")

    @property
    def headers(self):
        return {"Authorization": "Bearer " + self.config["engine_token"]}

    def entities(self):
        entities = []
        registry, devices, areas = er.async_get(self.hass), dr.async_get(self.hass), ar.async_get(self.hass)
        for entity_id in selected_entity_ids(self.hass, self.config):
            state = self.hass.states.get(entity_id)
            if not state or not async_should_expose(self.hass, "conversation", entity_id):
                continue
            record = registry.async_get(entity_id)
            area_id = record.area_id if record else None
            if not area_id and record and record.device_id:
                device = devices.async_get(record.device_id)
                area_id = device.area_id if device else None
            area = areas.async_get_area(area_id) if area_id else None
            entities.append({"entity_id": entity_id, "name": state.name, "state": state.state, "area": area.name if area else "", "aliases": list(record.aliases) if record else []})
        return entities

    async def async_stream(self, audio, language):
        # Refresh discovery every utterance so removed MCP tools are not retained.
        self.tools = await self.mcp.list_tools()
        candidates = build_candidates(self.entities(), self.tools)
        if not candidates:
            raise ValueError("No exposed, available entities have compatible MCP tools")
        gate = DecisionGate(candidates, self.config["threshold"], self.config.get("margin", 0))
        session_id = uuid.uuid4().hex
        outcome = "No action reached the configured probability threshold."
        latest_revision = 0
        latest_text = ""
        audio_bytes = 0
        partial_updates = 0
        score_updates = 0
        final_text = ""
        started = time.monotonic()
        action_task = None
        sender = None
        url = self.config["engine_url"].replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/stream"
        async with self.session.ws_connect(url, headers=self.headers, heartbeat=15, max_msg_size=1_000_000) as ws:
            self.websockets.add(ws)
            try:
                await ws.send_json({"type": "start", "session_id": session_id, "language": language, "sample_rate": 16000, "candidates": candidates, "stt": {"mode": self.config["stt_mode"], "url": self.config.get("stt_url", ""), "token": self.config.get("stt_token", "")}})

                async def send_audio():
                    nonlocal audio_bytes
                    try:
                        async for chunk in audio:
                            await ws.send_bytes(chunk)
                            audio_bytes += len(chunk)
                        await ws.send_json({"type": "end"})
                    except Exception:
                        await ws.close()
                        raise

                async def execute(candidate):
                    nonlocal outcome
                    entity_id = candidate["entity_id"]
                    try:
                        if not async_should_expose(self.hass, "conversation", entity_id):
                            raise ValueError("Entity is no longer exposed")
                        current = self.hass.states.get(entity_id)
                        if current is None or current.state in ("unavailable", "unknown"):
                            raise ValueError("Entity became unavailable")
                        await self.mcp.call(candidate["tool"], candidate["arguments"])
                        outcome = "Requested: " + candidate["label"] + "."
                        status = "accepted"
                    except Exception:
                        # A timed-out command may already have executed. Never retry.
                        outcome = "The action failed or could not be confirmed. It has not been retried."
                        status = "failed_or_unconfirmed"
                    self.hass.bus.async_fire(EVENT_ACTION, {"session_id": session_id, "entity_id": entity_id, "action": candidate["id"], "status": status})

                sender = asyncio.create_task(send_audio())
                complete = False
                async with asyncio.timeout(90):
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            if message.type == aiohttp.WSMsgType.ERROR:
                                raise RuntimeError("Truss stream disconnected")
                            continue
                        event = message.json()
                        if event.get("type") == "partial":
                            partial_updates += 1
                            latest_revision = event["revision"]
                            latest_text = event["text"]
                        elif event.get("type") == "probabilities":
                            if event.get("revision") != latest_revision:
                                prefix = event.get("text", "")
                                if not prefix or not latest_text.casefold().startswith(prefix.casefold() + " "):
                                    continue
                            probabilities = event.get("probabilities", {})
                            score_updates += 1
                            self.hass.bus.async_fire(EVENT_PROBABILITIES, {"session_id": session_id, "revision": event["revision"], "current_revision": latest_revision, "transcript": event.get("text", ""), "probabilities": probabilities, "score_scope": event.get("score_scope", "legacy_grouped"), "inference_ms": event.get("inference_ms"), "already_fired": gate.claimed})
                            if candidate := gate.select(probabilities):
                                # Keep reading partials while the MCP round-trip runs.
                                action_task = asyncio.create_task(execute(candidate))
                        elif event.get("type") == "error":
                            raise RuntimeError("Truss transcription or inference failed")
                        elif event.get("type") == "done":
                            final_text = event.get("text", "")
                            complete = True
                            break
                if not complete:
                    raise RuntimeError("Truss disconnected before completing the utterance")
                await sender
                if action_task:
                    await action_task
            finally:
                self.websockets.discard(ws)
                if sender and not sender.done():
                    sender.cancel()
                if sender:
                    await asyncio.gather(sender, return_exceptions=True)
                if action_task:
                    await asyncio.shield(action_task)
        if gate.claimed:
            result = "action_attempted"
        elif not audio_bytes:
            result = "no_audio"
            outcome = "No microphone audio reached Truss. Check microphone access and the Assist audio pipeline."
        elif not final_text.strip():
            result = "no_transcript"
            outcome = "Truss received audio but could not recognize speech. Check the microphone and whether Assist stopped recording too early."
        elif not score_updates:
            result = "no_scores"
            outcome = "Truss recognized speech but received no usable action scores. Check the engine logs."
        else:
            result = "below_threshold"
        summary = {"session_id": session_id, "audio_ms": round(audio_bytes / 32), "elapsed_ms": round((time.monotonic() - started) * 1000), "partial_updates": partial_updates, "score_updates": score_updates, "transcript_chars": len(final_text), "result": result}
        self.hass.bus.async_fire("truss_session", summary)
        log = _LOGGER.warning if result in ("no_audio", "no_transcript", "no_scores") else _LOGGER.debug
        log("Truss session: result=%s audio_ms=%s elapsed_ms=%s partials=%s scores=%s transcript_chars=%s", result, summary["audio_ms"], summary["elapsed_ms"], partial_updates, score_updates, len(final_text))
        self.receipts = {key: value for key, value in self.receipts.items() if value[0] > time.monotonic()}
        if len(self.receipts) >= 100:
            self.receipts.pop(next(iter(self.receipts)))
        receipt = RECEIPT_PREFIX + session_id
        self.receipts[receipt] = (time.monotonic() + 120, outcome)
        return receipt

    def consume_receipt(self, receipt):
        item = self.receipts.pop(receipt.strip(), None)
        return item[1] if item and item[0] > time.monotonic() else None

    async def async_close(self):
        await asyncio.gather(*(ws.close() for ws in list(self.websockets)), return_exceptions=True)
        self.receipts.clear()
