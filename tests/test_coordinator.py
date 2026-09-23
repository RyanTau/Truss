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

    async def test_text_skips_transcription_and_executes_once(self):
        def forbidden(*args):
            raise AssertionError("Text must not initialize or call speech recognition")
        models = self.engine_app["engine"].models
        models.create_stream = models.transcribe = forbidden
        outcome = await self.coordinator.async_text("turn on kitchen", "en")
        self.assertTrue(outcome.startswith("Requested:"))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.coordinator.receipts)

    async def test_partial_scores_flow_before_audio_ends_below_threshold(self):
        received = asyncio.Event()
        transcripts = iter(["Turn", "Turn on", "Turn on kitchen"])
        engine = self.engine_app["engine"]
        engine.models.transcribe = lambda *args: next(transcripts)
        engine.models.score = lambda text, candidates: {c["id"]: {"Turn": .1, "Turn on": .3, "Turn on kitchen": .7}[text] for c in candidates}
        def fire(name, data):
            self.events.append((name, data))
            if name == "truss_probabilities":
                received.set()
        self.hass.bus.async_fire = fire
        async def audio():
            for _ in range(2):
                received.clear()
                yield bytes(2560)
                await asyncio.wait_for(received.wait(), 3)
                self.assertEqual(self.calls, [])
        await asyncio.wait_for(self.coordinator.async_stream(audio(), "en"), 5)
        scores = [data for name, data in self.events if name == "truss_probabilities"]
        self.assertEqual([data["transcript"] for data in scores], ["Turn", "Turn on", "Turn on kitchen"])
        self.assertEqual([next(iter(data["probabilities"].values())) for data in scores], [.1, .3, .7])
        self.assertEqual(self.calls, [])

    async def test_text_below_threshold_and_invalid_text(self):
        self.engine_app["engine"].models.score = lambda text, candidates: {c["id"]: .4 for c in candidates}
        self.assertIn("No action reached", await self.coordinator.async_text("kitchen on", "en"))
        self.assertIn("1–1000", await self.coordinator.async_text(" " * 3, "en"))
        self.assertIn("1–1000", await self.coordinator.async_text("x" * 1001, "en"))
        self.assertEqual(self.calls, [])

    async def test_high_scores_still_published_for_negations_and_state_questions(self):
        for text in ("Do not turn on kitchen", "Don't turn on kitchen", "Is kitchen on?", "turn kitchen off"):
            with self.subTest(text=text):
                outcome = await self.coordinator.async_text(text, "en")
                self.assertFalse(outcome.startswith("Requested:"))
                event = [data for name, data in self.events if name == "truss_probabilities"][-1]
                self.assertEqual(event["transcript"], text)
                self.assertEqual(event["probabilities"], {"light.kitchen:on": .99})
                self.assertEqual(self.calls, [])

    async def test_assist_scope_refreshes_exposure_and_filters_domains(self):
        self.coordinator.config.update(entity_mode="assist", entities=["light.old"])
        ids = ["light.kitchen", "switch.desk", "sensor.temperature", "light.hidden"]
        self.hass.states.async_all = lambda: [types.SimpleNamespace(entity_id=item) for item in ids]
        self.hass.exposed = set(ids[:-1])
        self.assertEqual([e["entity_id"] for e in self.coordinator.entities()], ["light.kitchen", "switch.desk"])
        self.hass.exposed.remove("light.kitchen")
        self.assertEqual([e["entity_id"] for e in self.coordinator.entities()], ["switch.desk"])

    async def test_area_scope_uses_entity_override_and_device_fallback(self):
        # patch.dict removes imported modules when its context exits; use the
        # resolver retained by the coordinator with its original HA doubles.
        selection = types.SimpleNamespace(**load_coordinator().selected_entity_ids.__globals__)
        records = {
            "light.kitchen": types.SimpleNamespace(area_id="kitchen", device_id="bed_device"),
            "switch.desk": types.SimpleNamespace(area_id=None, device_id="bed_device"),
            "light.unassigned": types.SimpleNamespace(area_id=None, device_id=None),
        }
        self.hass.states.async_all = lambda: [types.SimpleNamespace(entity_id=item) for item in records]
        self.hass.exposed = set(records)
        with patch.object(selection.er, "async_get", return_value=types.SimpleNamespace(async_get=records.get)), patch.object(selection.dr, "async_get", return_value=types.SimpleNamespace(async_get=lambda key: types.SimpleNamespace(area_id="bedroom"))):
            self.assertEqual(selection.selected_entity_ids(self.hass, {"entity_mode": "areas", "areas": ["kitchen"]}), ["light.kitchen"])
            self.assertEqual(selection.selected_entity_ids(self.hass, {"entity_mode": "areas", "areas": ["bedroom"]}), ["switch.desk"])
            self.assertEqual(selection.selected_entity_ids(self.hass, {"entity_mode": "areas", "areas": []}), [])

    async def test_automatic_scope_over_limit_fails_before_execution(self):
        self.coordinator.config["entity_mode"] = "assist"
        ids = ["light.room_" + str(i) for i in range(25)]
        self.hass.exposed = set(ids)
        self.hass.states.async_all = lambda: [types.SimpleNamespace(entity_id=item) for item in ids]
        with self.assertRaisesRegex(ValueError, "at most 24"):
            await self.coordinator.async_stream(self.audio_until_action(), "en")
        self.assertEqual(self.calls, [])

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

    async def test_empty_audio_is_not_reported_as_threshold_failure(self):
        self.engine_app["engine"].models.transcribe = lambda *args: ""

        async def empty_audio():
            if False:
                yield b""

        receipt = await self.coordinator.async_stream(empty_audio(), "en")
        self.assertIn("No microphone audio", self.coordinator.consume_receipt(receipt))
        summary = [data for name, data in self.events if name == "truss_session"][-1]
        self.assertEqual(summary["result"], "no_audio")
        self.assertEqual(summary["audio_ms"], 0)
        self.assertEqual(summary["score_updates"], 0)
        self.assertEqual(self.calls, [])

    async def test_audio_without_transcript_reports_recognition_failure(self):
        self.engine_app["engine"].models.transcribe = lambda *args: ""

        async def silence():
            yield bytes(32000)

        receipt = await self.coordinator.async_stream(silence(), "en")
        self.assertIn("could not recognize speech", self.coordinator.consume_receipt(receipt))
        summary = [data for name, data in self.events if name == "truss_session"][-1]
        self.assertEqual(summary["result"], "no_transcript")
        self.assertEqual(summary["audio_ms"], 1000)
        self.assertEqual(self.calls, [])

    async def test_recognized_command_below_threshold_has_scores(self):
        self.engine_app["engine"].models.score = lambda text, candidates: {c["id"]: .5 for c in candidates}

        async def audio():
            yield bytes(32000)

        receipt = await self.coordinator.async_stream(audio(), "en")
        self.assertIn("No action reached", self.coordinator.consume_receipt(receipt))
        summary = [data for name, data in self.events if name == "truss_session"][-1]
        self.assertEqual(summary["result"], "below_threshold")
        self.assertGreater(summary["score_updates"], 0)
        self.assertGreater(summary["transcript_chars"], 0)
        self.assertNotIn("transcript", summary)
        self.assertEqual(self.calls, [])
