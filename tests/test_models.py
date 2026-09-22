"""Verify grouping and ID mapping without substituting claims of model accuracy."""
import unittest
from support import integration
from engine.models import LocalModels


class RecordingAgent:
    def __init__(self):
        self.calls = []

    def predict(self, text, questions):
        self.calls.append((text, questions))
        keys = list(questions["action"]["criteria"])
        scores = {key: .2 / (len(keys) - 1) for key in keys}
        scores[keys[1]] = .8
        return {"answers": {"action": {"probabilities": scores}}}


class ModelAdapterTests(unittest.TestCase):
    def test_groups_keep_all_ids_and_explicit_wait(self):
        models = LocalModels({})
        models.agent = RecordingAgent()
        candidates = [{"id": f"entity{i}:on", "label": f"Turn on Lamp {i}", "area": "Kitchen", "aliases": ["ceiling light"]} for i in range(7)]
        scores = models.score("TURN ON LAMP 0", candidates)
        self.assertEqual(set(scores), {c["id"] for c in candidates})
        self.assertEqual(scores["entity0:on"], .8)
        self.assertEqual(scores["entity4:on"], .8)
        self.assertEqual(len(models.agent.calls), 2)
        for text, questions in models.agent.calls:
            self.assertEqual(text, "TURN ON LAMP 0")
            question = questions["action"]
            self.assertEqual(question["type"], "choice")
            self.assertIn("wait", question["criteria"])
            self.assertLessEqual(len(question["criteria"]), 5)
            self.assertIn("ceiling light", list(question["criteria"].values())[1])
