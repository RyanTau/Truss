"""Capability discovery, staged evidence and exact local value binding."""
from copy import deepcopy
import unittest

from support import integration
from engine.controls import score_controls, validate_controls, ControlScores
from engine.server import validate_start

controls = integration("controls")
catalog = integration("catalog")


def thermostat(**attributes):
    return {"entity_id": "climate.study", "name": "Study thermostat", "state": "heat", "temperature_unit": "C",
            "attributes": {"supported_features": 1, "min_temp": 16, "max_temp": 30, "target_temp_step": .5, **attributes}}


def temperature_controls():
    return controls.build_controls([thermostat()], [], {"climate": {"set_temperature": {}}})


class DiscoveryTests(unittest.TestCase):
    def test_temperature_feature_range_step_and_exact_service_binding(self):
        candidate, = temperature_controls()
        self.assertEqual(candidate["control"]["type"], "score")
        values = [o["value"] for o in candidate["control"]["options"]]
        self.assertEqual(values, [16 + i * .5 for i in range(29)])
        resolved = controls.resolve_value(candidate, 19.5)
        self.assertEqual(resolved["service"], "climate.set_temperature")
        self.assertEqual(resolved["arguments"], {"entity_id": "climate.study", "temperature": 19.5})
        self.assertNotIn("temperature", candidate["arguments"])
        for bad in (35.0, 19.25, "19.5", True):
            with self.assertRaises(ValueError):
                controls.resolve_value(candidate, bad)

    def test_unknown_steps_ranges_features_and_services_not_guessed(self):
        for attrs in ({"supported_features": 2}, {"target_temp_step": None}, {"min_temp": float("nan")},
                      {"target_temp_step": .001}, {"target_temp_step": 0}):
            self.assertEqual(controls.build_controls([thermostat(**attrs)], [], {"climate": {"set_temperature": {}}}), [])
        self.assertEqual(controls.build_controls([thermostat()], [], {}), [])

    def test_live_choices_and_volume_unit_conversion(self):
        entity = {"entity_id": "media_player.tv", "name": "TV", "state": "on", "attributes": {
            "supported_features": 2048 | 4, "source_list": ["HDMI 1", "News", "Channel 7"]}}
        candidates = controls.build_controls([entity], [], {"media_player": {"select_source": {}, "volume_set": {}}})
        source = next(c for c in candidates if c["control"]["attribute"] == "source")
        self.assertEqual(source["control"]["type"], "choice")
        self.assertEqual(controls.resolve_value(source, "Channel 7")["arguments"]["source"], "Channel 7")
        volume = next(c for c in candidates if c["control"]["attribute"] == "volume")
        self.assertEqual(controls.resolve_value(volume, 40.0)["arguments"]["volume_level"], .4)
        entity["attributes"]["supported_features"] = 0
        self.assertEqual(controls.build_controls([entity], [], {"media_player": {"select_source": {}, "volume_set": {}}}), [])

    def test_capability_types_and_no_inferred_current_state_ranges(self):
        entities = [
            {"entity_id": "light.lamp", "name": "Lamp", "attributes": {"supported_color_modes": ["brightness"]}},
            {"entity_id": "cover.blind", "name": "Blind", "attributes": {"supported_features": 4}},
            {"entity_id": "select.program", "name": "Program", "attributes": {"options": ["A", "B"]}},
            {"entity_id": "number.rate", "name": "Rate", "attributes": {"min": 1, "max": 3, "step": .5}},
        ]
        services = {"light": {"turn_on": {}}, "cover": {"set_cover_position": {}},
                    "select": {"select_option": {}}, "number": {"set_value": {}}}
        candidates = controls.build_controls(entities, [], services)
        validate_controls(candidates)
        self.assertEqual({c["control"]["type"] for c in candidates}, {"binary", "choice", "score"})
        entities[0]["attributes"] = {"brightness": 120, "supported_color_modes": ["onoff"]}
        self.assertFalse(any(c["control"]["attribute"] == "brightness" for c in controls.build_controls(entities, [], services)))

    def test_mcp_power_controls_keep_exact_target(self):
        tools = [{"name": "HassTurn" + op, "inputSchema": {"properties": {"name": {}}}} for op in ("On", "Off")]
        candidates = controls.build_controls([{"entity_id": "light.desk", "name": "Desk"}], tools, {})
        self.assertEqual([c["control"]["value"] for c in candidates], [True, False])
        self.assertEqual(candidates[0]["arguments"], {"name": "light.desk"})

    def test_fractional_fan_step_includes_maximum_and_binary_cover(self):
        fan = {"entity_id": "fan.office", "name": "Fan", "attributes": {"supported_features": 1, "percentage_step": 100 / 3}}
        candidates = controls.build_controls([fan], [], {"fan": {"set_percentage": {}}})
        self.assertEqual([o["value"] for o in candidates[0]["control"]["options"]], [0, 33, 67, 100])
        cover = {"entity_id": "cover.door", "name": "Door", "attributes": {"supported_features": 3}}
        candidates = controls.build_controls([cover], [], {"cover": {"open_cover": {}, "close_cover": {}}})
        validate_controls(candidates)
        self.assertEqual([c["control"]["value"] for c in candidates], [100.0, 0.0])


class Agent:
    def __init__(self, choices, probabilities=None):
        self.choices = list(choices)
        self.probabilities = probabilities or {}
        self.calls = []

    def predict(self, text, questions):
        stage, question = next(iter(questions.items()))
        self.calls.append((text, stage, question))
        choice = self.choices.pop(0)
        keys = list(question["criteria"]) if question["type"] == "choice" else [str(i) for i in range(len(question["criteria"]))]
        selected = keys[choice]
        probability = self.probabilities.get(stage, .99)
        scores = {k: probability if k == selected else (1 - probability) / (len(keys) - 1) for k in keys}
        answer = {"type": question["type"], "probabilities": scores, "confidence": .4}
        if question["type"] == "choice":
            answer["choice"] = selected
        else:
            answer["score"] = sum(i * scores[str(i)] for i in range(len(keys)))
        return {"answers": {stage: answer}}


class StagedTests(unittest.TestCase):
    def test_score_path_and_raw_evidence_reach_the_gate(self):
        candidates = temperature_controls()
        agent = Agent([1, 1, 1, 0, 7], {"device": .91})
        result = score_controls(agent, "Set study to 19.5", candidates)
        self.assertEqual(result.decision["value"], 19.5)
        self.assertEqual(result.decision["attribute"], "temperature")
        self.assertAlmostEqual(result[candidates[0]["id"]], .91)
        self.assertEqual([s["stage"] for s in result.trace], ["request", "device", "attribute", "value.ready", "value"])
        selected = catalog.DecisionGate(candidates, .9, .05).select(result, "set study to 19.5", result.decision)
        self.assertEqual(selected["arguments"]["temperature"], 19.5)
        self.assertIsNone(catalog.DecisionGate(candidates, .95).select(result, "set study to 19.5", result.decision))

    def test_wait_at_each_stage_and_missing_values_never_execute(self):
        for decisions in ([0], [1, 0], [1, 1, 0], [1, 1, 1, 1]):
            result = score_controls(Agent(decisions), "set study to", temperature_controls())
            self.assertIsNone(result.decision)
            self.assertTrue(all(p == 0 for p in result.values()))
        candidate = temperature_controls()[0]
        self.assertIsNone(catalog.DecisionGate([candidate], .5).select({candidate["id"]: 1}))

    def test_binary_value_and_choice_values_use_choice_questions(self):
        candidates = controls.build_controls([{"entity_id": "light.desk", "name": "Desk"}], [], {"light": {"turn_on": {}, "turn_off": {}}})
        # Candidate sort order is off then on.
        result = score_controls(Agent([1, 1, 1, 1]), "turn desk off", candidates)
        self.assertIs(result.decision["value"], False)
        self.assertEqual(result.decision["candidate_id"], "light.desk:off")
        self.assertEqual([s["question"]["type"] for s in result.trace], ["choice"] * 4)

    def test_margin_includes_wait_and_other_values(self):
        candidates = temperature_controls()
        result = score_controls(Agent([1, 1, 1, 0, 7], {"request": .51}), "set study to 19.5", candidates)
        self.assertIsNone(catalog.DecisionGate(candidates, .5, .05).select(result, "set study", result.decision))

    def test_unknown_value_invalid_decision_and_no_retry(self):
        candidates = temperature_controls()
        result = score_controls(Agent([1, 1, 1, 0, 7]), "set study to 19.5", candidates)
        for changes in ({"value": 99.0}, {"attribute": "other"}, {"candidate_id": "other"}, {"margin": float("nan")}, {"probability": True}):
            gate = catalog.DecisionGate(candidates, .9)
            self.assertIsNone(gate.select(result, "set study", {**result.decision, **changes}))
            self.assertFalse(gate.claimed)
        gate = catalog.DecisionGate(candidates, .9)
        self.assertIsNotNone(gate.select(result, "set study", result.decision))
        self.assertIsNone(gate.select(result, "set study", result.decision))

    def test_malformed_controls_and_distributions_fail_closed(self):
        for mutate in (lambda c: c["control"].update(type="arbitrary"),
                       lambda c: c["control"]["options"][0].update(value=float("nan")),
                       lambda c: c["control"]["options"].reverse()):
            candidates = temperature_controls()
            mutate(candidates[0])
            with self.assertRaises(ValueError):
                validate_start({"type": "start", "sample_rate": 16000, "candidates": candidates, "stt": {"mode": "text"}, "text": "hello"})
        class BadAgent:
            def predict(self, text, questions):
                return {"answers": {"request": {"choice": "A device action is requested", "probabilities": {"A device action is requested": 1}}}}
        with self.assertRaises(ValueError):
            score_controls(BadAgent(), "set study", temperature_controls())
