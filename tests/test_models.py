"""Selection invariants; these doubles do not establish real model accuracy."""
import unittest
from support import integration
from engine.models import LocalModels
from engine.names import hotword_text


def lamp_candidates():
    catalog = integration("catalog")
    tools = [{"name": "HassTurn" + op, "inputSchema": {"properties": {"name": {}}}} for op in ("On", "Off")]
    return catalog.build_candidates([
        {"entity_id": "light.ball", "name": "Ball lamp", "aliases": ["Turkish lamp"]},
        {"entity_id": "light.tall", "name": "Dining room tall lamp", "aliases": ["Tall lamp"]},
        {"entity_id": "light.colour", "name": "Colour light"},
    ], tools)


class RecordingAgent:
    def __init__(self):
        self.calls = []

    def predict(self, text, questions):
        self.calls.append((text, questions))
        return {"answers": {"action": {"probabilities": {key: 1 / len(questions["action"]["criteria"]) for key in questions["action"]["criteria"]}}}}


class ModelAdapterTests(unittest.TestCase):
    def setUp(self):
        self.models = LocalModels({})
        self.models.agent = RecordingAgent()
        self.candidates = lamp_candidates()

    def test_every_partial_reaches_laya_and_scores_all_actions(self):
        for text in ("Turn", "Turn on", "Turn on the tal", "Turn on the tall lamp",
                     "Do not turn on the tall lamp", "Is the tall lamp on?"):
            scores = self.models.score(text, self.candidates)
            self.assertEqual(set(scores), {c["id"] for c in self.candidates})
            self.assertTrue(all(score > 0 for score in scores.values()))
        self.assertEqual(len(self.models.agent.calls), 6)
        self.assertEqual(self.models.agent.calls[0][0], "TURN")
        question = self.models.agent.calls[0][1]["action"]
        self.assertEqual(len(question["criteria"]), len(self.candidates) + 1)
        self.assertIn("wait", question["criteria"])
        self.assertTrue(any("lamp" in key for key in question["criteria"]))

    def test_order_stable_and_one_distribution_even_at_limit(self):
        original = self.models.score("Turn", self.candidates)
        self.assertEqual(original, self.models.score("Turn", list(reversed(self.candidates))))
        self.assertEqual(self.models.agent.calls[0][1], self.models.agent.calls[1][1])
        candidates = [{"id": f"light.lamp{i}:on", "entity_id": f"light.lamp{i}", "label": f"Turn on lamp {i}"} for i in range(48)]
        self.assertEqual(len(self.models.score("Turn", candidates)), 48)
        self.assertEqual(len(self.models.agent.calls[-1][1]["action"]["criteria"]), 49)

    def test_raw_probabilities_not_zeroed_or_renormalized(self):
        def predict(text, questions):
            return {"answers": {"action": {"probabilities": {
                key: .7 if key == "wait" else .05 for key in questions["action"]["criteria"]
            }}}}
        self.models.agent.predict = predict
        scores = self.models.score("Turn", self.candidates)
        self.assertTrue(all(score == .05 for score in scores.values()))
        self.assertAlmostEqual(sum(scores.values()), .3)

    def test_duplicate_names_remain_separate_choices(self):
        for candidate in self.candidates:
            candidate["name"] = "Lamp"
            candidate["aliases"] = []
        scores = self.models.score("lamp on", self.candidates)
        self.assertEqual(len(scores), 6)
        self.assertEqual(len(self.models.agent.calls[-1][1]["action"]["criteria"]), 7)

    def test_hotwords_are_deduplicated_and_do_not_accept_control_syntax(self):
        class Tokenizer:
            def encode(self, text, out_type):
                return [1]
            def unk_id(self):
                return 0
        hints = hotword_text(self.candidates, Tokenizer()).split("/")
        self.assertEqual(len(hints), len(set(hints)))
        self.assertIn("TURKISH LAMP", hints)
        self.assertIn("TALL LAMP", hints)
        injected = hotword_text([{"label": "Turn on Foo/bar:99\nBaz", "aliases": []}], Tokenizer())
        self.assertEqual(injected, "FOO BAR BAZ")

    def test_per_stream_hints_are_not_shared(self):
        class Tokenizer:
            def encode(self, text, out_type):
                return [1]
            def unk_id(self):
                return 0
        class Recognizer:
            def create_stream(self, hotwords=""):
                return hotwords
        self.models.speech_tokenizer = Tokenizer()
        self.models.recognizer = Recognizer()
        first = self.models.create_stream(self.candidates[:2])
        second = self.models.create_stream(self.candidates[2:4])
        self.assertIn("TURKISH LAMP", first)
        self.assertNotIn("TURKISH LAMP", second)
        self.assertIn("TALL LAMP", second)
