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
        return {"answers": {"action": {"probabilities": {"wait": .03, "execute": .97}}}}


class ModelAdapterTests(unittest.TestCase):
    def setUp(self):
        self.models = LocalModels({})
        self.models.agent = RecordingAgent()
        self.candidates = lamp_candidates()

    def test_named_device_and_operation_are_only_eligible_action(self):
        for text, winner in (("Turn the tall lamp on", "light.tall:on"),
                             ("Turn off the Turkish lamp", "light.ball:off"),
                             ("Turn off the color light", "light.colour:off")):
            with self.subTest(text=text):
                scores = self.models.score(text, self.candidates)
                self.assertEqual(set(scores), {c["id"] for c in self.candidates})
                self.assertEqual(scores[winner], .97)
                self.assertEqual(sum(scores.values()), .97)
        self.assertEqual(len(self.models.agent.calls), 3)
        self.assertEqual(self.models.agent.calls[1][1]["action"]["criteria"]["execute"], "Turn off Turkish lamp")

    def test_abstains_on_incomplete_unknown_negated_and_multiple_targets(self):
        for text in ("Turn on", "Tall lamp", "THUNDER TALL LAMP ON", "TURN OFF THE COLORED LION",
                     "Do not turn on the tall lamp", "Don't turn on the tall lamp",
                     "Turn the tall lamp on and off", "Turn on the tall lamp and ball lamp",
                     "Is the tall lamp on?", "Turn on the tall lamppost"):
            with self.subTest(text=text):
                self.assertFalse(any(self.models.score(text, self.candidates).values()))
        self.assertEqual(self.models.agent.calls, [])

    def test_shared_alias_abstains(self):
        for c in self.candidates:
            c["aliases"] = ["My lamp"]
        self.assertFalse(any(self.models.score("Turn on my lamp", self.candidates).values()))
        self.assertEqual(self.models.agent.calls, [])

    def test_choice_does_not_depend_on_candidate_order_or_unrelated_devices(self):
        original = self.models.score("Turn off the tall lamp", self.candidates)
        reversed_scores = self.models.score("Turn off the tall lamp", list(reversed(self.candidates)))
        extra = {"id": "switch.other:on", "entity_id": "switch.other", "name": "Desk fan", "label": "Turn on Desk fan"}
        extended = self.models.score("Turn off the tall lamp", [extra, *self.candidates])
        self.assertEqual(original, reversed_scores)
        self.assertEqual(original, {key: extended[key] for key in original})
        self.assertEqual(self.models.agent.calls[0][1], self.models.agent.calls[2][1])

    def test_scene_and_script_activation(self):
        for domain in ("scene", "script"):
            c = {"id": f"{domain}.movie:on", "entity_id": f"{domain}.movie", "label": "Activate Movie mode"}
            self.assertEqual(self.models.score("Activate movie mode", [c])[c["id"]], .97)
            self.assertEqual(self.models.score("Turn off movie mode", [c])[c["id"]], 0)
            self.assertEqual(self.models.score("Activate movie mode and turn it off", [c])[c["id"]], 0)

    def test_probability_is_not_renormalized_to_force_an_action(self):
        self.models.agent.predict = lambda *args: {"answers": {"action": {"probabilities": {"wait": .7, "execute": .3}}}}
        scores = self.models.score("Turn off the colour light", self.candidates)
        self.assertEqual(scores["light.colour:off"], .3)

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
