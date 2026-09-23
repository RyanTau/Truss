"""Device vocabulary shared by local transcription and choice formatting."""
import re
from difflib import SequenceMatcher


def normalize(text):
    return " ".join(re.findall(r"\w+", text.casefold().replace("colour", "color").replace("colored", "color")))


def device_names(candidate):
    name = candidate.get("name") or re.sub(r"^(?:Turn (?:on|off)|Activate)\s+", "", candidate["label"], flags=re.I)
    return list(dict.fromkeys([name, *candidate.get("aliases", [])]))


def mentioned_name(text, candidate):
    utterance = " " + normalize(text) + " "
    matches = [name for name in device_names(candidate) if normalize(name) and " " + normalize(name) + " " in utterance]
    return max(matches, key=lambda name: len(normalize(name)), default=None)


def resolve_target(text, candidates):
    """Match names, unique shortened names, or close word-level misspellings."""
    matches = {}
    for candidate in candidates:
        name = mentioned_name(text, candidate)
        if name:
            matches[candidate["entity_id"]] = name
    if matches:
        return next(iter(matches.items())) if len(matches) == 1 else None
    words = normalize(text).split()
    ranked = {}
    for candidate in candidates:
        for name in device_names(candidate):
            tokens = normalize(name).split()
            variants = [tokens, *[tokens[i:] for i in range(1, len(tokens) - 1)]]
            for variant in variants:
                for start in range(len(words) - len(variant) + 1):
                    heard = words[start:start + len(variant)]
                    similarities = [SequenceMatcher(None, a, b).ratio() if min(len(a), len(b)) >= 3 else float(a == b) for a, b in zip(variant, heard)]
                    if not similarities or min(similarities) < .8:
                        continue
                    score = sum(similarities) / len(similarities)
                    if score < .85:
                        continue
                    key = candidate["entity_id"]
                    if score > ranked.get(key, (0, ""))[0]:
                        ranked[key] = (score, " ".join(heard))
    ordered = sorted(ranked.items(), key=lambda item: item[1][0], reverse=True)
    if not ordered or (len(ordered) > 1 and ordered[0][1][0] - ordered[1][1][0] < .1):
        return None
    return ordered[0][0], ordered[0][1][1]


def resolve_action(text, candidates):
    """Resolve only explicit supported commands; unknown/ambiguous input waits."""
    if re.search(r"\b(?:not|never|don['’]?t|dont|cancel)\b", text, flags=re.I):
        return None
    target = resolve_target(text, candidates)
    if target is None:
        return None
    entity_id, name = target
    # Don't mistake an on/off word inside a device name for the requested action.
    remaining = (" " + normalize(text) + " ").replace(" " + normalize(name) + " ", " ")
    words = set(remaining.split())
    if re.match(r"^(?:is|are|was|were|what|why|when|whether)\b", remaining.strip()):
        return None
    if entity_id.split(".")[0] in ("scene", "script"):
        if words & {"off", "disable"}:
            return None
        operation = "on" if words & {"activate", "run", "start"} or ("turn" in words and "on" in words) else None
    else:
        operations = words & {"on", "off"}
        operations |= {"on"} if words & {"enable", "activate", "start"} else set()
        operations |= {"off"} if words & {"disable", "deactivate", "stop"} else set()
        operation = next(iter(operations)) if len(operations) == 1 else None
    eligible = [c for c in candidates if c["entity_id"] == entity_id and c["id"].rsplit(":", 1)[-1] == operation]
    return (eligible[0], name) if len(eligible) == 1 else None


def hotword_text(candidates, tokenizer):
    # Exclude sherpa's '/' and ':' control syntax from user-defined names.
    phrases = set()
    for candidate in candidates:
        for name in device_names(candidate):
            clean = " ".join(re.findall(r"[A-Z]+(?:'[A-Z]+)?", name.upper()))
            if not clean:
                continue
            ids = tokenizer.encode(clean, out_type=int)
            if tokenizer.unk_id() in ids:
                continue
            phrases.add(clean)
    return "/".join(sorted(phrases))
