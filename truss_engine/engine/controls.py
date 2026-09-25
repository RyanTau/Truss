"""Configuration-driven action -> device -> attribute -> value evaluation."""
import math

CONTROL_SCHEMA = "device_attributes_v1"
SCORE_SCOPE = "staged_minimum"


class ControlScores(dict):
    def __init__(self, candidates):
        super().__init__((c["id"], 0.0) for c in candidates)
        self.trace = []
        self.decision = None
        self.score_scope = SCORE_SCOPE


def validate_controls(candidates):
    if not 1 <= len(candidates) <= 192 or len({c["entity_id"] for c in candidates}) > 24:
        raise ValueError("Expected at most 24 devices and 192 controls")
    groups, count = {}, 0
    for candidate in candidates:
        control = candidate.get("control")
        if not isinstance(control, dict):
            raise ValueError("Cannot mix legacy candidates and typed controls")
        for key in ("attribute", "description"):
            if not isinstance(control.get(key), str) or not 1 <= len(control[key]) <= 160:
                raise ValueError("Invalid control description")
        kind = control.get("type")
        if kind not in ("binary", "choice", "score"):
            raise ValueError("Unknown control type")
        if not isinstance(control.get("unit", ""), str) or len(control.get("unit", "")) > 40:
            raise ValueError("Invalid control unit")
        variable = "options" in control
        options = control["options"] if variable else [{"value": control.get("value"), "label": control.get("value_label")}]
        if not isinstance(options, list) or not 1 <= len(options) <= 128:
            raise ValueError("Expected 1-128 supported values")
        values = []
        for option in options:
            if not isinstance(option, dict) or not isinstance(option.get("label"), str) or not 1 <= len(option["label"]) <= 160:
                raise ValueError("Invalid option label")
            value = option.get("value")
            if type(value) not in (str, bool, int, float) or (type(value) is str and len(value) > 160) or (type(value) in (int, float) and not math.isfinite(value)):
                raise ValueError("Invalid option value")
            if any(type(value) is type(v) and value == v for v in values):
                raise ValueError("Duplicate option value")
            values.append(value)
        if kind == "binary" and (len(values) > 2 or any(type(v) is not bool for v in values)):
            raise ValueError("Binary controls require booleans")
        if kind == "score" and (not variable or len(values) < 2 or any(type(v) not in (int, float) for v in values) or any(a >= b for a, b in zip(values, values[1:]))):
            raise ValueError("Score controls require an ordered numeric scale")
        group = (candidate["entity_id"], control["attribute"])
        if group in groups:
            previous = groups[group]
            if variable or "options" in previous or previous["type"] != kind or previous["description"] != control["description"]:
                raise ValueError("Conflicting attribute definitions")
        groups[group] = control
        count += len(options)
    if count > 4096:
        raise ValueError("Too many configured values")


def score_controls(agent, text, candidates):
    """No device-specific logic. Returned values always originate in the catalogue.

    Scores are the minimum probability along the selected path, not a joint
    action distribution. Raw questions/results are retained in the trace.
    """
    validate_controls(candidates)
    result = ControlScores(candidates)
    path_probabilities, path_margins = [], []
    context = {"text": text}

    def ask(stage, instructions, labels, kind="choice"):
        # All internal keys stay out of LAYA's natural-language choices.
        keys = list(labels)
        rendered = {}
        for key, label in labels.items():
            display = label if label not in rendered else f"{label} ({key})"
            rendered[display] = key
        question = {"type": kind, "instructions": instructions,
                    "criteria": list(labels.values()) if kind == "score" else dict.fromkeys(rendered)}
        answer = agent.predict(text.upper(), {stage: question})["answers"][stage]
        probabilities = answer.get("probabilities", {})
        expected = {str(i) for i in range(len(keys))} if kind == "score" else set(rendered)
        if (set(probabilities) != expected or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
                or abs(sum(probabilities.values()) - 1) > .02):
            raise ValueError("Invalid staged probability distribution")
        if kind == "score":
            score = answer.get("score")
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= len(keys) - 1:
                raise ValueError("Invalid score level")
            selected = max(probabilities, key=probabilities.get)
            chosen = keys[int(selected)]
        else:
            selected = answer.get("choice")
            if selected not in rendered or probabilities[selected] < max(probabilities.values()) - 1e-6:
                raise ValueError("Invalid staged choice")
            chosen = rendered[selected]
        probability = probabilities[selected]
        competitors = [p for key, p in probabilities.items() if key != selected]
        path_probabilities.append(probability)
        path_margins.append(probability - max(competitors, default=0))
        result.trace.append({"stage": stage, "context": dict(context), "question": question,
                             "result": answer, "selected": chosen})
        return chosen

    if ask("request", "Is this a command to control a device?",
           {"wait": "No device action requested", "act": "A device action is requested"}) == "wait":
        return result
    devices = {}
    # Keep the attribute order supplied by discovery, as in the standalone
    # configuration; sorting executable IDs would reorder the questions.
    for candidate in candidates:
        devices.setdefault(candidate["entity_id"], []).append(candidate)
    labels = {"wait": "Device cannot yet be determined"}
    for entity_id, controls in sorted(devices.items()):
        sample = controls[0]
        names = [sample.get("name") or entity_id, *sample.get("aliases", [])]
        labels[entity_id] = ", ".join(names) + (f" in {sample['area']}" if sample.get("area") else "")
    device = ask("device", "Which device does the current request apply to?", labels)
    if device == "wait":
        return result
    context["device"] = device
    attributes = {}
    for candidate in devices[device]:
        attributes.setdefault(candidate["control"]["attribute"], []).append(candidate)
    attribute = ask("attribute", f"Which attribute of {labels[device]} does the current request ask to change?",
        {"wait": "No single supported attribute is specified", **{key: group[0]["control"]["description"] for key, group in attributes.items()}})
    if attribute == "wait":
        return result
    context["attribute"] = attribute
    group = attributes[attribute]
    control = group[0]["control"]
    options = []
    for candidate in group:
        for option in candidate["control"].get("options", [{"value": candidate["control"].get("value"), "label": candidate["control"].get("value_label")} ]):
            options.append((candidate, option))
    if control["type"] == "binary":
        options.sort(key=lambda item: item[1]["value"])
    subject = labels[device] + ": " + control["description"]
    option_labels = {str(i): o["label"] for i, (_, o) in enumerate(options)}
    if control["type"] == "score":
        ready = ask("value.ready", f"Does the current request specify a target for {subject}? Supported settings: " + "; ".join(option_labels.values()),
            {"specified": "A single supported target setting is requested", "wait": "Target missing, ambiguous, negated, unsupported or relative without a known target"})
        if ready == "wait":
            return result
        selected = ask("value", f"What target setting does the current request ask for {subject}?", option_labels, "score")
    else:
        selected = ask("value", f"What value does the current request ask to set for {subject}? Select only the requested value.",
            {"wait": "No single supported value requested, incomplete, ambiguous or negated", **option_labels})
        if selected == "wait":
            return result
    candidate, option = options[int(selected)]
    result[candidate["id"]] = min(path_probabilities)
    result.decision = {"candidate_id": candidate["id"], "device": device, "attribute": attribute,
                       "value": option["value"], "probability": min(path_probabilities), "margin": min(path_margins)}
    return result
