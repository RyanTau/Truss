"""Experimental staged LAYA evaluation; returns decisions, never executes actions."""
from copy import deepcopy
import re


class TranscriptRewrite(ValueError):
    """ASR changed already accepted text; caller must reconcile before resetting."""


class RequestEval:
    static_questions = (
        "Has the user specified a new request sufficiently to identify its intent?",
        "What device is involved in the unanswered request?",
        "What action needs to be performed on that device?",
    )
    static_answers = (("in_progress", "completed"), ("not_specified",), ("not_specified",))
    # Keep conjunctions with the pending request. Do not split device names on 'and'.
    separator = re.compile(r"\s+(?=(?:and\s+then|after\s+that|then)\b)", re.I)
    leading_connector = re.compile(r"^(?:and\s+then|after\s+that|then)\b[,\s]*", re.I)

    def __init__(self, request="", *, router, devices, actions):
        """devices: ID->description; actions: device ID->{action ID:description}.

        Action descriptions must include required values, e.g. set_temperature_19.
        LAYA selects supplied choices; it does not generate arbitrary parameters.
        Call update() with each full cumulative ASR transcript, not a token delta.
        """
        if not devices or set(devices) != set(actions) or any(not a for a in actions.values()):
            raise ValueError("Provide devices and nonempty actions for every device")
        if "not_specified" in devices or any("not_specified" in a for a in actions.values()):
            raise ValueError("not_specified is reserved")
        self.router = router
        self.devices, self.actions = deepcopy(devices), deepcopy(actions)
        self.reset()
        self.request = request

    def reset(self):
        self.request = ""
        self.state = {"answered": "", "unanswered": ""}
        self.answer_key = []
        self.answers = {}
        self.waiting_for = "request"
        self._last_transcript = None

    def _question(self, stage, criteria, instructions):
        return {stage: {"type": "choice", "instructions": instructions, "criteria": criteria}}

    def evaluate(self, stage, criteria, instructions, context):
        result = self.router.predict(deepcopy(context), self._question(stage, criteria, instructions))
        answer = result["answers"][stage]
        if not isinstance(answer, dict) or answer.get("choice") not in criteria:
            raise ValueError("Invalid LAYA answer for " + stage)
        self.answers[stage] = deepcopy(answer)
        return answer["choice"]

    def update(self, transcript):
        if not isinstance(transcript, str) or len(transcript) > 1000:
            raise ValueError("Expected a cumulative transcript of at most 1000 characters")
        transcript = transcript.strip()
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
                "in_progress": "No new request yet, or only an incomplete linking phrase",
                "completed": "A new request has begun; proceed to identify its device and action",
            }, self.static_questions[0] + " Evaluate only unanswered; answered is past context.", context)
            if status == "in_progress":
                break
            context["answers"] = deepcopy(self.answers)
            self.waiting_for = "device"
            device = self.evaluate("device", {"not_specified": "Device cannot yet be determined", **self.devices},
                self.static_questions[1] + " Resolve 'it' from answered and answer_key when unambiguous. Do not guess a missing device.", context)
            if device == "not_specified":
                break
            context["answers"] = deepcopy(self.answers)
            self.waiting_for = "action"
            action = self.evaluate("action", {"not_specified": "Action or a required parameter is missing, ambiguous, or negated", **self.actions[device]},
                self.static_questions[2] + " Evaluate only unanswered for the selected device. Require all parameters; 'set it to' is incomplete. Allow spelling/transcription errors when intent is clear.", context)
            if action == "not_specified":
                break
            record = {"device": device, "action": action, "text": clause, "answers": deepcopy(self.answers)}
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
                         "waiting_for": self.waiting_for})

    def eval_loop(self, transcripts=None):
        """Yield one result per live transcript; do not busy-loop on old audio."""
        for transcript in transcripts if transcripts is not None else [self.request]:
            yield self.update(transcript)
