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
from .controls import build_controls, resolve_value, CONTROL_SCHEMA
from .const import DOMAIN, EVENT_ACTION, EVENT_PROBABILITIES, RECEIPT_PREFIX
from .mcp import MCPClient
from .selection import selected_entity_ids

_LOGGER = logging.getLogger(__name__)
CONVERSATION_SCHEMA = "completed_pending_v1"


class TrussCoordinator:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.config = {**entry.data, **entry.options}
        self.session = async_get_clientsession(hass)
        self.mcp = MCPClient(self.session, self.config["mcp_url"], self.config["mcp_token"])
        self.tools = []
        self.receipts = {}
        self.websockets = set()
        self.typed_controls = False
        self.conversation_controls = False
        self.conversations = {}
        self.text_lock = asyncio.Lock()

    async def async_connect(self):
        await self.mcp.initialize()
        self.tools = await self.mcp.list_tools()
        async with self.session.get(self.config["engine_url"] + "/health", headers=self.headers, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            health = await response.json()
            if health.get("protocol") != "truss-v1" or not health.get("ready"):
                raise ValueError("Truss models are not ready")
            self.typed_controls = health.get("control_schema") == CONTROL_SCHEMA
            self.conversation_controls = self.typed_controls and health.get("conversation_schema") == CONVERSATION_SCHEMA

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
            units = getattr(getattr(self.hass, "config", None), "units", None)
            entities.append({"entity_id": entity_id, "name": state.name, "state": state.state,
                "area": area.name if area else "", "aliases": list(record.aliases) if record else [],
                "attributes": dict(getattr(state, "attributes", {})),
                "temperature_unit": str(getattr(units, "temperature_unit", ""))})
        return entities

    def candidates(self):
        if not self.typed_controls:
            return build_candidates(self.entities(), self.tools)
        registry = getattr(self.hass, "services", None)
        services = registry.async_services() if registry else {}
        return build_controls(self.entities(), self.tools, services)

    async def async_text(self, text, language, conversation_id=None, user_id=None):
        if not text.strip() or len(text) > 1000:
            return "Please enter a command of 1–1000 characters."
        # Serialize follow-ups so each sees the previous turn's completed state.
        async with self.text_lock:
            self.conversations = {key: item for key, item in self.conversations.items() if item[0] > time.monotonic()}
            key = (user_id, conversation_id) if conversation_id else None
            if text.strip() == "/reset":
                self.conversations.pop(key, None)
                return "Conversation context cleared."
            context = self.conversations.get(key, (0, {"completed": "", "pending": ""}))[1]
            if self.conversation_controls and len(" ".join(part for part in (*context.values(), text.strip()) if part)) > 1000:
                return "This conversation is full. Send /reset to start a new request."
            try:
                receipt = await self.async_stream(None, language, text=text, context_key=key)
            except BaseException:
                self.conversations.pop(key, None)
                raise
            return self.consume_receipt(receipt)

    async def async_stream(self, audio, language, *, text=None, context_key=None):
        # Refresh discovery every utterance so removed MCP tools are not retained.
        self.tools = await self.mcp.list_tools()
        candidates = self.candidates()
        if not candidates:
            raise ValueError("No exposed, available entities have compatible controls")
        gate = DecisionGate(candidates)
        contextual = self.conversation_controls and all("control" in c for c in candidates)
        context = self.conversations.get(context_key, (0, {"completed": "", "pending": ""}))[1] if context_key else {"completed": "", "pending": ""}
        next_context = None
        seen_decisions = set()
        action_failed = False
        context_invalid = False
        requested = []
        action_attempts = 0
        session_id = uuid.uuid4().hex
        outcome = "No executable action was selected."
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
                await ws.send_json({"type": "start", "session_id": session_id, "language": language, "sample_rate": 16000, "candidates": candidates,
                    **({"conversation_schema": CONVERSATION_SCHEMA, "context": context} if contextual else {}),
                    **({"text": text} if text is not None else {}), "stt": {"mode": "text" if text is not None else self.config["stt_mode"], "url": self.config.get("stt_url", ""), "token": self.config.get("stt_token", "")}})

                async def send_audio():
                    nonlocal audio_bytes
                    if text is not None:
                        return
                    try:
                        async for chunk in audio:
                            await ws.send_bytes(chunk)
                            audio_bytes += len(chunk)
                        await ws.send_json({"type": "end"})
                    except Exception:
                        await ws.close()
                        raise

                async def execute(candidate, previous=None, decision_id=None):
                    nonlocal outcome, action_failed, action_attempts
                    if previous:
                        await previous
                    if action_failed or context_invalid:
                        return  # Do not act on context dependent on an unconfirmed action.
                    action_attempts += 1
                    entity_id = candidate["entity_id"]
                    try:
                        if not async_should_expose(self.hass, "conversation", entity_id):
                            raise ValueError("Entity is no longer exposed")
                        current = self.hass.states.get(entity_id)
                        if current is None or current.state in ("unavailable", "unknown"):
                            raise ValueError("Entity became unavailable")
                        # Rebuild from live capabilities/scope before binding a value.
                        fresh = next((c for c in self.candidates() if c["id"] == candidate["id"]), None)
                        if fresh is None:
                            raise ValueError("Control is no longer available or selected")
                        if "control" in fresh:
                            value = candidate.get("selected_value", candidate["control"].get("value"))
                            fresh = resolve_value(fresh, value)
                        candidate = fresh
                        if "service" in candidate:
                            domain, service = candidate["service"].split(".", 1)
                            async with asyncio.timeout(15):
                                await self.hass.services.async_call(domain, service, candidate["arguments"], blocking=True)
                        else:
                            await self.mcp.call(candidate["tool"], candidate["arguments"])
                        requested.append(candidate["label"])
                        outcome = "Requested: " + "; ".join(requested) + "."
                        status = "accepted"
                    except Exception:
                        # A timed-out command may already have executed. Never retry.
                        action_failed = True
                        outcome = (("Requested: " + "; ".join(requested) + ". ") if requested else "") + "The action failed or could not be confirmed. It has not been retried."
                        if contextual:
                            outcome += " Remaining actions were stopped; conversation context was cleared."
                        status = "failed_or_unconfirmed"
                    self.hass.bus.async_fire(EVENT_ACTION, {"session_id": session_id, "entity_id": entity_id, "action": candidate["id"],
                        "attribute": candidate.get("control", {}).get("attribute"), "value": candidate.get("selected_value"), "status": status,
                        **({"decision_id": decision_id} if decision_id is not None else {})})

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
                            if contextual and event.get("conversation_schema") != CONVERSATION_SCHEMA:
                                raise RuntimeError("Engine omitted negotiated conversation metadata")
                            if event.get("revision") != latest_revision:
                                prefix = event.get("text", "")
                                if not prefix or not latest_text.casefold().startswith(prefix.casefold() + " "):
                                    continue
                            probabilities = event.get("probabilities", {})
                            score_updates += 1
                            self.hass.bus.async_fire(EVENT_PROBABILITIES, {"session_id": session_id, "revision": event["revision"], "current_revision": latest_revision, "transcript": event.get("text", ""), "probabilities": probabilities, "score_scope": event.get("score_scope", "legacy_grouped"), "decision_backend": event.get("decision_backend", "laya"), "inference_ms": event.get("inference_ms"), "already_fired": gate.claimed})
                            if event.get("score_scope") == "staged_minimum":
                                self.hass.bus.async_fire("truss_decision", {"session_id": session_id, "revision": event["revision"],
                                    "transcript": event.get("text", ""), "trace": event.get("trace", []), "decision": event.get("decision"),
                                    "decision_id": event.get("decision_id"), "context": event.get("context")})
                                if event.get("decision") is None:
                                    continue
                            selection_gate, action_text = gate, latest_text
                            decision_id = None
                            if contextual:
                                decision_id = event.get("decision_id")
                                if type(decision_id) is not int or not 1 <= decision_id <= 32:
                                    raise RuntimeError("Invalid conversation decision ID")
                                if decision_id in seen_decisions:
                                    continue
                                if decision_id != len(seen_decisions) + 1:
                                    raise RuntimeError("Out-of-order conversation decision")
                                seen_decisions.add(decision_id)
                                action_text = event.get("action_text")
                                spoken = " ".join(part for part in (context["pending"], latest_text) if part)
                                if not isinstance(action_text, str) or not action_text.strip() or action_text.casefold() not in spoken.casefold():
                                    raise RuntimeError("Decision does not match the current transcript")
                                selection_gate = DecisionGate(candidates)
                            if candidate := selection_gate.select(probabilities, action_text, event.get("decision")):
                                gate.claimed = True
                                # Keep reading partials while the MCP round-trip runs.
                                action_task = asyncio.create_task(execute(candidate, action_task, decision_id))
                            elif contextual:
                                context_invalid = True
                                gate.blocked_reason = selection_gate.blocked_reason or "A conversation decision could not be validated."
                                # Later decisions may rely on this rejected prediction.
                                raise RuntimeError("Conversation decision rejected")
                        elif event.get("type") == "error":
                            raise RuntimeError("Truss transcription or inference failed")
                        elif event.get("type") == "done":
                            final_text = event.get("text", "")
                            if contextual:
                                next_context = event.get("context")
                                if (not isinstance(next_context, dict) or set(next_context) != {"completed", "pending"}
                                        or any(not isinstance(v, str) for v in next_context.values())
                                        or len(" ".join(next_context.values()).strip()) > 1000):
                                    # Empty-audio sessions legitimately have no evaluation.
                                    if final_text.strip():
                                        raise RuntimeError("Invalid final conversation context")
                                    next_context = context
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
        if contextual and context_key:
            if action_failed or context_invalid:
                self.conversations.pop(context_key, None)
            elif next_context is not None:
                if context_key not in self.conversations and len(self.conversations) >= 100:
                    self.conversations.pop(next(iter(self.conversations)))
                self.conversations[context_key] = (time.monotonic() + 600, next_context)
        if gate.claimed:
            result = "action_attempted"
        elif gate.blocked_reason:
            result = "execution_blocked"
            outcome = gate.blocked_reason + " No action was taken."
        elif text is None and not audio_bytes:
            result = "no_audio"
            outcome = "No microphone audio reached Truss. Check microphone access and the Assist audio pipeline."
        elif not final_text.strip():
            result = "no_transcript"
            outcome = "Truss received audio but could not recognize speech. Check the microphone and whether Assist stopped recording too early."
        elif not score_updates:
            result = "no_scores"
            outcome = "Truss recognized speech but received no usable action scores. Check the engine logs."
        else:
            result = "no_action_selected"
        summary = {"session_id": session_id, "audio_ms": round(audio_bytes / 32), "elapsed_ms": round((time.monotonic() - started) * 1000), "partial_updates": partial_updates, "score_updates": score_updates, "transcript_chars": len(final_text), "result": result, "action_attempts": action_attempts}
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
        self.conversations.clear()
