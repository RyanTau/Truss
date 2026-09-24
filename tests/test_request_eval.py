import unittest
from copy import deepcopy
from support import integration
from engine.request_eval import RequestEval, TranscriptRewrite


class Router:
    def __init__(self):
        self.calls = []
        self.choices = []

    def predict(self, context, questions):
        stage = next(iter(questions))
        self.calls.append((deepcopy(context), stage))
        choice = self.choices.pop(0)
        return {"answers": {stage: {"choice": choice, "confidence": .9}}}


class RequestEvalTests(unittest.TestCase):
    def setUp(self):
        self.router = Router()
        self.evaluator = RequestEval(router=self.router,
            devices={"dyson": "Dyson", "lights": "Lights"},
            actions={"dyson": {"on": "Turn on", "19": "Set to 19 degrees"}, "lights": {"off": "Turn off"}})

    def feed(self, text, choices):
        self.router.choices = list(choices)
        result = self.evaluator.update(text)
        self.assertFalse(self.router.choices)
        return result

    def test_each_gate_stops_later_questions(self):
        self.feed("and then", ["in_progress"])
        self.assertEqual([c[1] for c in self.router.calls], ["request"])
        self.router.calls.clear()
        self.feed("turn on", ["completed", "not_specified"])
        self.assertEqual([c[1] for c in self.router.calls], ["request", "device"])
        self.feed("set Dyson to", ["completed", "dyson", "not_specified"])
        self.assertEqual(self.evaluator.waiting_for, "action")
        self.assertEqual(self.evaluator.answer_key, [])

    def test_user_sequence_keeps_accepted_context_and_pending_suffix(self):
        first = "Turn the Dyson on"
        self.feed(first, ["completed", "dyson", "on"])
        for suffix, choices in [
            ("and then", ["in_progress"]),
            ("and then set", ["completed", "dyson", "not_specified"]),
            ("and then set it to", ["completed", "dyson", "not_specified"]),
        ]:
            result = self.feed(first + " " + suffix, choices)
            self.assertEqual(result["context"], {"answered": first, "unanswered": suffix})
            self.assertEqual(result["completed"], [])
        full = first + " and then set it to 19 degrees"
        result = self.feed(full, ["completed", "dyson", "19"])
        self.assertEqual(result["context"], {"answered": full, "unanswered": ""})
        self.assertEqual(result["completed"][0]["action"], "19")
        context = self.router.calls[-1][0]
        self.assertEqual(context["answer_key"][0]["device"], "dyson")
        self.assertEqual(context["answers"]["device"]["choice"], "dyson")
        final = self.feed(full + " After that, turn of lights", ["completed", "lights", "off"])
        self.assertEqual(len(final["answer_key"]), 3)
        repeat = self.feed(self.evaluator.request, [])
        self.assertEqual(repeat["completed"], [])

    def test_multiple_clauses_in_one_update_and_isolated_snapshots(self):
        result = self.feed("Turn the Dyson on and then set it to", ["completed", "dyson", "on", "completed", "dyson", "not_specified"])
        self.assertEqual(result["context"], {"answered": "Turn the Dyson on", "unanswered": "and then set it to"})
        result["answer_key"].clear()
        self.assertEqual(len(self.evaluator.answer_key), 1)

    def test_pending_rewrites_re_evaluate_device_and_committed_rewrites_stop(self):
        self.feed("set lights", ["completed", "lights", "not_specified"])
        result = self.feed("set Dyson to 19 degrees", ["completed", "dyson", "19"])
        self.assertEqual(result["completed"][0]["device"], "dyson")
        with self.assertRaises(TranscriptRewrite):
            self.evaluator.update("set Dyson to 20 degrees")
        self.evaluator.reset()
        self.assertEqual(self.evaluator.answer_key, [])

    def test_bad_model_choice_cannot_complete_a_request(self):
        with self.assertRaises(ValueError):
            self.feed("Turn on Dyson", ["unknown"])
        self.assertEqual(self.evaluator.answer_key, [])
