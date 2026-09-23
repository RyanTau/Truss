"""Device vocabulary for per-session transcription hints."""
import re
from difflib import SequenceMatcher


def device_names(candidate):
    name = candidate.get("name") or re.sub(r"^(?:Turn (?:on|off)|Activate)\s+", "", candidate["label"], flags=re.I)
    return list(dict.fromkeys([name, *candidate.get("aliases", [])]))


def action_label(text, candidate):
    """Use the most relevant spoken name to label each option, never filter it."""
    def words(value):
        return re.findall(r"\w+", value.casefold().replace("colour", "color"))
    heard = words(text)
    names = device_names(candidate)
    def similarity(name):
        tokens = words(name)
        return max((SequenceMatcher(None, " ".join(tokens), " ".join(heard[i:i + len(tokens)])).ratio()
                    for i in range(len(heard))), default=0)
    # Aliases are usually shorter and more natural spoken names. All names
    # remain available, including when the user speaks the full friendly name.
    preferred = [*candidate.get("aliases", []), names[0]]
    name = max(preferred, key=similarity)
    verb = "Activate" if candidate["entity_id"].split(".")[0] in ("scene", "script") else "Turn " + candidate["id"].rsplit(":", 1)[-1]
    return verb + " " + name


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
