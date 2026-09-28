"""Conversation state, ASR transactions and wire validation without real models."""
import asyncio
import unittest

from engine.conversation import ControlConversation, CONVERSATION_SCHEMA
from engine.request_eval import TranscriptRewrite
from engine.server import validate_start
from engine.streaming import LiveDecisions
from test_controls import Agent, temperature_controls


EMPTY = {"completed": "", "pending": ""}


class ContextualControlTests(unittest.TestCase):
    def test_chained_actions_use_history_and_supported_numeric_values(self):
        agent = Agent([1, 1, 1, 0, 7, 1, 1, 1, 0, 8])
        session = ControlConversation(agent, temperature_controls(), EMPTY)
        result = session.evaluate("set study to 19.5 then set it to 20")
        self.assertEqual([e["decision"]["value"] for e in result.events], [19.5, 20])
        self.assertEqual([e["decision_id"] for e in result.events], [1, 2])
        self.assertEqual(result.events[1]["action_text"], "then set it to 20")
        self.assertIn("Completed actions: SET STUDY TO 19.5", agent.calls[5][0])
        self.assertIn("In progress request: THEN SET IT TO 20", agent.calls[5][0])
        self.assertTrue(agent.calls[0][2]["instructions"].startswith("Classify only the new In progress request."))
        # Draft scoring cannot consume text until the stream confirms freshness.
        self.assertEqual(session.evaluator.state["answered"], "")
        result.commit()
        repeat = session.evaluate("set study to 19.5 then set it to 20")
        self.assertIsNone(repeat.events[0]["decision"])
        self.assertEqual(repeat.state["pending"], "")

    def test_followup_restores_completed_and_pending_text(self):
        agent = Agent([1, 1, 1, 0, 8])
        session = ControlConversation(agent, temperature_controls(),
            {"completed": "set study to 19.5", "pending": "actually set it to"})
        result = session.evaluate("20")
        self.assertEqual(result.events[0]["decision"]["value"], 20)
        self.assertIn("In progress request: ACTUALLY SET IT TO 20", agent.calls[0][0])
        self.assertEqual(result.state["completed"], "set study to 19.5 actually set it to 20")

    def test_wait_preserves_pending_and_committed_rewrite_fails(self):
        session = ControlConversation(Agent([1, 1, 1, 0, 7, 0]), temperature_controls(), EMPTY)
        session.evaluate("set study to 19.5").commit()
        result = session.evaluate("set study to 19.5 actually")
        self.assertIsNone(result.events[0]["decision"])
        self.assertEqual(result.state["pending"], "actually")
        with self.assertRaises(TranscriptRewrite):
            session.evaluate("set study to 20")

    def test_malformed_context_or_unnegotiated_context_rejected(self):
        start = {"type": "start", "sample_rate": 16000, "stt": {"mode": "text"},
            "text": "set study to 20", "candidates": temperature_controls(),
            "conversation_schema": CONVERSATION_SCHEMA, "context": EMPTY}
        validate_start(start)
        for context in (None, {}, {"completed": False, "pending": ""}, {"completed": "x" * 1001, "pending": ""}):
            with self.assertRaises(ValueError):
                validate_start({**start, "context": context})
        del start["conversation_schema"]
        with self.assertRaises(ValueError):
            validate_start(start)


class ContextualStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_draft_is_not_committed_and_appended_text_does_not_repeat(self):
        session = ControlConversation(Agent([1, 1, 1, 0, 7, 1, 1, 1, 0, 8, 0]), temperature_controls(), EMPTY)
        first_scored, release = asyncio.Event(), asyncio.Event()
        events = []

        async def score(text, candidates):
            result = session.evaluate(text)
            if text == "set study to 19.5":
                first_scored.set()
                await release.wait()
            return result

        async def emit(event):
            events.append(event)

        live = LiveDecisions(score, emit, temperature_controls())
        task = asyncio.create_task(live.run())
        await live.update("set study to 19.5")
        await asyncio.wait_for(first_scored.wait(), 2)
        await live.update("set study to 20")
        release.set()
        # Wait for the replacement to be committed before appending filler.
        for _ in range(100):
            if live.context is not None:
                break
            await asyncio.sleep(.001)
        self.assertEqual(session.evaluator.state["answered"], "set study to 20")
        await live.update("set study to 20 please")
        live.finish()
        await asyncio.wait_for(task, 2)
        decisions = [e for e in events if e.get("decision") is not None]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["decision_id"], 1)
        self.assertEqual(decisions[0]["decision"]["value"], 20)
