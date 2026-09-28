"""Map discovered controls to the standalone evaluator and stage session state."""
from copy import copy, deepcopy

from .controls import validate_controls, ControlScores
from .request_eval import LocalQuestionRouter, RequestEval

CONVERSATION_SCHEMA = "completed_pending_v1"
MAX_ACTIONS = 32


def validate_context(context):
    if not isinstance(context, dict) or set(context) != {"completed", "pending"}:
        raise ValueError("Expected completed/pending conversation context")
    if any(not isinstance(value, str) for value in context.values()):
        raise ValueError("Conversation context must contain text")
    if len(context["completed"]) + len(context["pending"]) > 1000:
        raise ValueError("Conversation context exceeds 1000 characters")


def catalogue(candidates):
    validate_controls(candidates)
    devices, bindings = {}, {}
    for candidate in candidates:
        entity_id, control = candidate["entity_id"], candidate["control"]
        names = [candidate.get("name") or entity_id, *candidate.get("aliases", [])]
        description = ", ".join(names) + (f" in {candidate['area']}" if candidate.get("area") else "")
        device = devices.setdefault(entity_id, {"description": description, "attributes": {}})
        attribute = control["attribute"]
        spec = device["attributes"].setdefault(attribute, {"description": control["description"],
            "type": control["type"], "unit": control.get("unit", ""), "options": []})
        for option in control.get("options", [{"value": control.get("value"), "label": control.get("value_label")} ]):
            value = option["value"]
            key = (entity_id, attribute, type(value), value)
            if key in bindings:
                raise ValueError("Ambiguous control value binding")
            bindings[key] = candidate["id"]
            spec["options"].append(deepcopy(option))
    for device in devices.values():
        for spec in device["attributes"].values():
            if spec["type"] == "binary":
                spec["options"].sort(key=lambda option: option["value"])
    return devices, bindings


class Evaluation:
    def __init__(self, owner, trial, events, state):
        self.owner, self.trial, self.events, self.state = owner, trial, events, state

    def commit(self):
        # Called on the event loop only after the scored ASR prefix is validated.
        self.owner.evaluator = self.trial


class ControlConversation:
    """One instance per socket; no mutable conversation state on shared models."""
    def __init__(self, agent, candidates, context):
        validate_context(context)
        devices, self.bindings = catalogue(candidates)
        self.candidates = candidates
        self.evaluator = RequestEval(router=LocalQuestionRouter(agent), devices=devices)
        completed, pending = context["completed"].strip(), context["pending"].strip()
        self.prefix = " ".join(part for part in (completed, pending) if part)
        self.evaluator.state = {"answered": completed, "unanswered": pending}
        self.evaluator.request = self.prefix

    def evaluate(self, text):
        trial = copy(self.evaluator)
        for name in ("state", "answer_key", "answers", "trace"):
            setattr(trial, name, deepcopy(getattr(trial, name)))
        trial.router = LocalQuestionRouter(self.evaluator.router.agent)
        result = trial.update(" ".join(part for part in (self.prefix, text.strip()) if part))
        if len(trial.answer_key) > MAX_ACTIONS:
            raise ValueError("At most 32 decisions per utterance")
        first = len(trial.answer_key) - len(result["completed"])
        events = []
        for index, record in enumerate(result["completed"], first + 1):
            probabilities, margins = [], []
            for answer in record["answers"].values():
                ranked = sorted(answer["probabilities"].values(), reverse=True)
                probabilities.append(ranked[0])
                margins.append(ranked[0] - (ranked[1] if len(ranked) > 1 else 0))
            candidate_id = self.bindings[(record["device"], record["attribute"], type(record["value"]), record["value"])]
            scores = ControlScores(self.candidates)
            scores[candidate_id] = min(probabilities)
            scores.decision = {"candidate_id": candidate_id, "device": record["device"],
                "attribute": record["attribute"], "value": record["value"],
                "probability": min(probabilities), "margin": min(margins)}
            events.append({"probabilities": dict(scores), "decision": scores.decision,
                "decision_id": index, "action_text": record["text"]})
        if not events:
            events.append({"probabilities": dict(ControlScores(self.candidates)), "decision": None})
        state = {"completed": result["context"]["answered"], "pending": result["context"]["unanswered"]}
        for event in events:
            event.update(score_scope="staged_minimum", conversation_schema=CONVERSATION_SCHEMA,
                         trace=result["trace"], context=state)
        return Evaluation(self, trial, events, state)
