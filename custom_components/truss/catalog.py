"""Build concrete actions from actual entities and discovered MCP schemas."""
from __future__ import annotations

import math
from .const import MAX_ENTITIES, SUPPORTED_DOMAINS


def find_tool(tools: list, intent: str):
    matches = [t for t in tools if t.get("name", "").split("__")[-1] == intent]
    if len(matches) != 1:
        return None
    tool = matches[0]
    schema = tool.get("inputSchema", {})
    if "name" not in schema.get("properties", {}) or set(schema.get("required", [])) - {"name"}:
        return None
    return tool["name"]


def build_candidates(entities: list, tools: list) -> list:
    if len(entities) > MAX_ENTITIES:
        raise ValueError(f"Select at most {MAX_ENTITIES} entities")
    on, off = find_tool(tools, "HassTurnOn"), find_tool(tools, "HassTurnOff")
    candidates = []
    for entity in entities:
        entity_id = entity["entity_id"]
        domain = entity_id.split(".")[0]
        if domain not in SUPPORTED_DOMAINS or entity.get("state") in ("unavailable", "unknown"):
            continue
        for operation, tool in (("on", on), ("off", off)):
            if not tool or (operation == "off" and domain in ("scene", "script")):
                continue
            verb = "Activate" if domain in ("scene", "script") else f"Turn {operation}"
            candidates.append({
                "id": f"{entity_id}:{operation}", "entity_id": entity_id,
                "label": f"{verb} {entity['name']}", "area": entity.get("area", ""),
                "aliases": entity.get("aliases", [])[:8], "state": entity.get("state", ""),
                "tool": tool, "arguments": {"name": entity_id},
            })
    return candidates


class DecisionGate:
    """At most one execution per utterance; never retry ambiguous tool outcomes."""
    def __init__(self, candidates: list, threshold: float, margin: float = 0):
        self.candidates = {c["id"]: c for c in candidates}
        self.threshold = threshold
        self.margin = margin
        self.claimed = False

    def select(self, probabilities: dict):
        if self.claimed or not isinstance(probabilities, dict):
            return None
        # A partial/malformed score vector must not win by hiding competitors.
        if set(probabilities) != set(self.candidates):
            return None
        if any(isinstance(p, bool) or not isinstance(p, (float, int)) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()):
            return None
        ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None
        winner, probability = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        if probability < self.threshold or probability - second < self.margin or (len(ranked) > 1 and probability == second):
            return None
        self.claimed = True
        return self.candidates[winner]
