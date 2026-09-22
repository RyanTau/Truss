import asyncio
import unittest
from support import integration
from engine.streaming import LiveDecisions

catalog = integration("catalog")


def tools():
    return [{"name": "homeassistant__" + name, "inputSchema": {"properties": {"name": {"type": "string"}}}} for name in ("HassTurnOn", "HassTurnOff")]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.entities = [{"entity_id": "light.kitchen", "name": "Kitchen light", "state": "off"}]

    def test_discovered_tools_and_exact_entity(self):
        candidates = catalog.build_candidates(self.entities, tools())
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["arguments"], {"name": "light.kitchen"})
        self.assertEqual(candidates[0]["tool"], "homeassistant__HassTurnOn")

    def test_missing_tools_unavailable_and_unsupported_entities(self):
        self.assertEqual(catalog.build_candidates(self.entities, []), [])
        self.entities[0]["state"] = "unavailable"
        self.assertEqual(catalog.build_candidates(self.entities, tools()), [])
        self.assertEqual(catalog.build_candidates([{"entity_id": "lock.front", "name": "Front", "state": "locked"}], tools()), [])

    def test_scene_activation_only(self):
        candidates = catalog.build_candidates([{"entity_id": "scene.movie", "name": "Movie", "state": "2026-09-21"}], tools())
        self.assertEqual([c["id"] for c in candidates], ["scene.movie:on"])

    def test_ambiguous_tool_and_extra_required_parameter_rejected(self):
        candidate_tools = tools()
        candidate_tools.append(candidate_tools[0])
        self.assertIsNone(catalog.find_tool(candidate_tools, "HassTurnOn"))
        candidate_tools = tools()
        candidate_tools[0]["inputSchema"]["required"] = ["name", "unsupported_parameter"]
        self.assertIsNone(catalog.find_tool(candidate_tools, "HassTurnOn"))

    def test_threshold_margin_and_exactly_once(self):
        gate = catalog.DecisionGate(catalog.build_candidates(self.entities, tools()), .95, .05)
        self.assertIsNone(gate.select({"light.kitchen:on": .94, "light.kitchen:off": .01}))
        self.assertIsNone(gate.select({"light.kitchen:on": .97, "light.kitchen:off": .94}))
        self.assertEqual(gate.select({"light.kitchen:on": .97, "light.kitchen:off": .01})["id"], "light.kitchen:on")
        self.assertIsNone(gate.select({"light.kitchen:on": .99, "light.kitchen:off": .01}))

    def test_malformed_scores_never_execute(self):
        for scores in ({"light.kitchen:on": .99}, {"other": 1}, {"light.kitchen:on": float("nan"), "light.kitchen:off": .0}, {"light.kitchen:on": True, "light.kitchen:off": 0}, {"light.kitchen:on": 1.1, "light.kitchen:off": 0}):
            gate = catalog.DecisionGate(catalog.build_candidates(self.entities, tools()), .95)
            self.assertIsNone(gate.select(scores))
            self.assertFalse(gate.claimed)


class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_inference_happens_before_finish(self):
        emitted = []
        scored = asyncio.Event()

        async def score(text, candidates):
            return {"on": .98}

        async def emit(event):
            emitted.append(event)
            if event["type"] == "probabilities":
                scored.set()

        live = LiveDecisions(score, emit, [{"id": "on"}])
        task = asyncio.create_task(live.run())
        await live.update("turn on the kitchen light")
        await asyncio.wait_for(scored.wait(), 2)
        self.assertFalse(live.ended)
        self.assertFalse(task.done())
        live.finish()
        await asyncio.wait_for(task, 2)
        self.assertEqual(len([e for e in emitted if e["type"] == "probabilities"]), 1)

    async def test_revisions_discard_stale_and_coalesce_pending(self):
        started, release = asyncio.Event(), asyncio.Event()
        scored_texts, emitted = [], []

        async def score(text, candidates):
            scored_texts.append(text)
            if len(scored_texts) == 1:
                started.set()
                await release.wait()
            return {"on": .99}

        async def emit(event):
            emitted.append(event)

        live = LiveDecisions(score, emit, [{"id": "on"}])
        task = asyncio.create_task(live.run())
        await live.update("turn on")
        await started.wait()
        await live.update("turn on kitchen")
        await live.update("do not turn on kitchen")
        release.set()
        live.finish()
        await asyncio.wait_for(task, 2)
        self.assertEqual(scored_texts, ["turn on", "do not turn on kitchen"])
        self.assertEqual([e["revision"] for e in emitted if e["type"] == "probabilities"], [3])

    async def test_empty_session_ends_without_inference(self):
        async def fail(*args):
            self.fail("No inference for empty speech")
        live = LiveDecisions(fail, fail, [{"id": "on"}])
        live.finish()
        await asyncio.wait_for(live.run(), 2)
