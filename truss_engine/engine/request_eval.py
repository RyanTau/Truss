"""Deployable conversation evaluator, ported from the standalone testing.py harness."""
import json
import math
from copy import deepcopy
import re


def validate_devices(devices):
    """Validate the declarative catalogue; no device names have special meaning."""
    if not isinstance(devices, dict) or not devices:
        raise ValueError("Configure at least one device")
    for device_id, device in devices.items():
        if device_id == "not_specified" or not isinstance(device, dict) or not device.get("description"):
            raise ValueError("Devices require a description and a non-reserved ID")
        attributes = device.get("attributes")
        if not isinstance(attributes, dict) or not attributes:
            raise ValueError("Each device requires attributes")
        for name, spec in attributes.items():
            if name == "not_specified" or not isinstance(spec, dict) or not spec.get("description"):
                raise ValueError("Attributes require a description and a non-reserved ID")
            kind, options = spec.get("type"), spec.get("options")
            if kind not in ("binary", "choice", "score") or not isinstance(options, list) or not options:
                raise ValueError("Attributes need binary, choice or score type and at least two options")
            if any(not isinstance(o, dict) or "value" not in o or not isinstance(o.get("label"), str) or not o["label"] for o in options):
                raise ValueError("Each option needs a value and a label")
            values = [o["value"] for o in options]
            if any(v is None or type(v) not in (str, int, float, bool) or (type(v) is float and not math.isfinite(v)) for v in values):
                raise ValueError("Option values must be finite numbers, strings or booleans")
            if len({json.dumps(v) for v in values}) != len(values) or len({o["label"] for o in options}) != len(options):
                raise ValueError("Option values and labels must be unique within an attribute")
            if kind == "binary" and (len(values) > 2 or any(type(v) is not bool for v in values)):
                raise ValueError("Binary attributes require boolean values")
            if kind == "score" and (len(values) < 2 or any(type(v) not in (int, float) for v in values) or any(a >= b for a, b in zip(values, values[1:]))):
                raise ValueError("Score values must be strictly increasing numbers")


class TranscriptRewrite(ValueError):
    """ASR changed already accepted text; caller must reconcile before resetting."""


class LocalQuestionRouter:
    """Keep internal IDs and probability dumps out of the model's input text."""

    def __init__(self, agent):
        self.agent = agent

    def predict(self, context, questions):
        # Keep the completed transcript visible as reference while making the
        # newly supplied request the clearly bounded text to classify.
        text = ("Completed actions: " + (context["answered"].upper() or "(none)")
                + "\nIn progress request: " + context["unanswered"].upper())
        rendered = deepcopy(questions)
        for question in rendered.values():
            question["instructions"] = (
                "Classify only the new In progress request. Completed actions are history"
                " and must not be repeated. " + question["instructions"] + " "
                "Use Completed only to resolve references such as it, them, or that."
            )
        mappings = {}
        for stage, question in rendered.items():
            if question["type"] == "choice":
                labels = {}
                for key, description in question["criteria"].items():
                    label = description or key
                    if label in labels:
                        label += " (" + key + ")"
                    labels[label] = key
                mappings[stage] = labels
                question["criteria"] = dict.fromkeys(labels)
        self.last_input, self.last_questions = text, deepcopy(rendered)
        result = self.agent.predict(text, rendered)
        # A malformed distribution must not hide a competing action.
        for stage, question in rendered.items():
            answer = result["answers"][stage]
            probabilities = answer.get("probabilities", {})
            expected = list(question["criteria"]) if question["type"] == "choice" else [str(i) for i in range(len(question["criteria"]))]
            if (not isinstance(probabilities, dict) or set(probabilities) != set(expected)
                    or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
                    or not math.isclose(sum(probabilities.values()), 1, abs_tol=.002)):
                raise ValueError("Invalid staged probability distribution")
            if question["type"] == "choice":
                answer["choice"] = max(expected, key=probabilities.get)
        for stage, labels in mappings.items():
            answer = result["answers"][stage]
            answer["choice"] = labels[answer["choice"]]
            if "probabilities" in answer:
                answer["probabilities"] = {labels[key]: value for key, value in answer["probabilities"].items()}
        return result


class RequestEval:
    # Separators delimit sequential requests without splitting device names on 'and'.
    separator = re.compile(r"\s+(?=(?:and\s+then|after\s+that|then)\b)", re.I)
    leading_connector = re.compile(r"^(?:and\s+then|after\s+that|then)\b[,\s]*", re.I)

    def __init__(self, request="", *, router, devices):
        """devices is the complete device/attribute/control configuration.

        LAYA chooses the device, attribute and supported value. Only the
        configuration determines available controls and their question types.
        update() accepts full cumulative transcripts, not token deltas.
        """
        validate_devices(devices)
        self.router = router
        self.devices = deepcopy(devices)
        self.reset()
        self.request = request

    def reset(self):
        self.request = ""
        self.state = {"answered": "", "unanswered": ""}
        self.answer_key = []
        self.answers = {}
        self.waiting_for = "request"
        self._last_transcript = None
        self.trace = []

    def _question(self, stage, criteria, instructions):
        return {stage: {"type": "choice", "instructions": instructions, "criteria": criteria}}

    def evaluate(self, stage, criteria, instructions, context):
        answer = self.ask(stage, self._question(stage, criteria, instructions), context)
        if not isinstance(answer, dict) or answer.get("choice") not in criteria:
            raise ValueError("Invalid LAYA answer for " + stage)
        self.answers[stage] = deepcopy(answer)
        return answer["choice"]

    def ask(self, stage, questions, context):
        result = self.router.predict(deepcopy(context), deepcopy(questions))
        answer = result["answers"][stage]
        self.trace.append({"stage": stage, "context": deepcopy(context),
                           "question": deepcopy(questions[stage]), "result": deepcopy(answer),
                           "model_input": self.router.last_input,
                           "model_question": deepcopy(self.router.last_questions[stage])})
        return answer

    def select_value(self, spec, context):
        self.waiting_for = "value"
        options = spec["options"]
        subject = context["device_description"] + ": " + spec["description"]
        if spec["type"] in ("binary", "choice"):
            criteria = {"not_specified": "No single supported value requested, incomplete, ambiguous or negated"}
            criteria.update({f"option_{i}": option["label"] for i, option in enumerate(options)})
            selected = self.evaluate("value", criteria,
                f"What value does the current request ask to set for {subject}? Select only the requested value.", context)
            if selected == "not_specified":
                return None
            value = options[int(selected.removeprefix("option_"))]["value"]
            self.answers["value"]["selected_value"] = value
            self.trace[-1]["result"] = deepcopy(self.answers["value"])
            return value

        unit = spec.get("unit", "")
        values = [option["value"] for option in options]
        scale = [f"{option['label']} ({option['value']} {unit})".strip() for option in options]
        ready = self.evaluate("value.ready", {
            "specified": "A single supported target setting is requested",
            "not_specified": "Target missing, ambiguous, negated, unsupported or relative without a known target",
        }, f"Does the current request specify a target for {subject}? Supported settings: " + "; ".join(scale), context)
        if ready != "specified":
            return None
        question = {"value": {"type": "score",
            "instructions": f"What target setting does the current request ask for {subject}?",
            "criteria": scale}}
        answer = self.ask("value", question, context)
        score = answer.get("score") if isinstance(answer, dict) else None
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= len(values) - 1:
            raise ValueError("Invalid LAYA score")
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != {str(i) for i in range(len(values))}:
            raise ValueError("Invalid LAYA score probabilities")
        weights = [probabilities[str(i)] for i in range(len(values))]
        if (any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in weights)
                or not math.isclose(sum(weights), 1, abs_tol=.002)):
            raise ValueError("Invalid LAYA score probabilities")
        lower = int(math.floor(score))
        upper = min(lower + 1, len(values) - 1)
        mapped = values[lower] + (score - lower) * (values[upper] - values[lower])
        # Use the most likely supported setting, not an average of alternatives.
        selected_index = max(range(len(values)), key=lambda i: weights[i])
        selected = values[selected_index]
        self.answers["value"] = {**deepcopy(answer), "mapped_value": round(mapped, 4),
            "selected_value": selected, "selected_probability": weights[selected_index],
            "selection_method": "highest_probability_score_level", "unit": unit}
        self.trace[-1]["result"] = deepcopy(self.answers["value"])
        return selected

    def continue_message(self, message):
        """Append a console message to the conversation, including pending text."""
        if not isinstance(message, str):
            raise ValueError("Expected a text message")
        transcript = " ".join(part for part in (self.request, message.strip()) if part)
        return self.update(transcript)

    def update(self, transcript):
        if not isinstance(transcript, str) or len(transcript) > 1000:
            raise ValueError("Expected a cumulative transcript of at most 1000 characters")
        transcript = transcript.strip()
        self.trace = []
        answered = self.state["answered"]
        if answered and not (transcript == answered or transcript.startswith(answered + " ")):
            raise TranscriptRewrite("ASR rewrote accepted text; reconcile decisions, then reset")
        if transcript == self._last_transcript:
            return self.snapshot([])
        self.request = transcript
        self.state["unanswered"] = transcript[len(answered):].strip()
        completed = []
        while self.state["unanswered"]:
            pending = self.state["unanswered"]
            leading = self.leading_connector.match(pending)
            boundary = self.separator.search(pending, leading.end() if leading else 0)
            clause = pending[:boundary.start()] if boundary else pending
            self.answers = {}
            context = {"answered": self.state["answered"], "unanswered": clause,
                       "answer_key": deepcopy(self.answer_key), "answers": {}}
            self.waiting_for = "request"
            status = self.evaluate("request", {
                "wait": "No device action requested",
                "act": "A device action is requested",
            }, "Is this a command to control a device?", context)
            if status == "wait":
                break
            self.waiting_for = "device"
            device = self.evaluate("device", {"not_specified": "Device cannot yet be determined",
                **{key: spec["description"] for key, spec in self.devices.items()}},
                "Which device does the in-progress request apply to? Resolve references using completed requests.", context)
            if device == "not_specified":
                break
            device_spec = self.devices[device]
            context["selected_device"] = device
            context["device_description"] = device_spec["description"]
            self.waiting_for = "attribute"
            attribute = self.evaluate("attribute", {"not_specified": "No single supported attribute is specified",
                **{key: spec["description"] for key, spec in device_spec["attributes"].items()}},
                "Which attribute of " + device_spec["description"] + " does the current request ask to change?", context)
            if attribute == "not_specified":
                break
            context["selected_attribute"] = attribute
            spec = device_spec["attributes"][attribute]
            value = self.select_value(spec, context)
            if value is None:
                break
            record = {"device": device, "attribute": attribute, "value": value,
                      "unit": spec.get("unit", ""), "text": clause, "answers": deepcopy(self.answers)}
            self.answer_key.append(record)
            completed.append(deepcopy(record))
            # Preserve the exact accepted prefix, including original whitespace.
            remaining = pending[boundary.end():].strip() if boundary else ""
            end = len(transcript) - len(remaining) if remaining else len(transcript)
            self.state = {"answered": transcript[:end].rstrip(), "unanswered": remaining}
            self.answers = {}
            self.waiting_for = "request"
        self._last_transcript = transcript
        return self.snapshot(completed)

    def snapshot(self, completed):
        return deepcopy({"context": self.state, "answers": self.answers,
                         "answer_key": self.answer_key, "completed": completed,
                         "waiting_for": self.waiting_for, "trace": self.trace})

    def eval_loop(self, transcripts=None):
        """Yield one result per live transcript; do not busy-loop on old audio."""
        for transcript in transcripts if transcripts is not None else [self.request]:
            yield self.update(transcript)
