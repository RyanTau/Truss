"""Translate HA capabilities into typed controls and locally owned service calls."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import math

from .catalog import build_candidates
from .const import MAX_ENTITIES

CONTROL_SCHEMA = "device_attributes_v1"
MAX_CONTROLS = 192
MAX_OPTIONS = 128


def numeric_options(low, high, step, unit=""):
    """Keep the actual device grid; never invent a coarser supported step."""
    try:
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high, step)):
            return []
        lo, hi, increment = map(lambda v: Decimal(str(v)), (low, high, step))
        if increment <= 0 or hi <= lo:
            return []
        count = int((hi - lo) // increment) + 1
        if not 2 <= count <= MAX_OPTIONS:
            return []
        values = [float(lo + i * increment) for i in range(count)]
        return [{"value": v, "label": f"{v:g} {unit}".strip()} for v in values]
    except (InvalidOperation, ValueError, OverflowError):
        return []


def choices(values):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_OPTIONS:
        return []
    if any(not isinstance(v, str) or not v or len(v) > 120 for v in values) or len(set(values)) != len(values):
        return []
    return [{"value": v, "label": v.replace("_", " ")} for v in values]


def build_controls(entities, tools, services):
    """services is HA's registered domain -> service mapping.

    Model-visible controls are declarative. HA domain knowledge and service
    argument conversions stay here, outside the model's decision algorithm.
    """
    if len(entities) > MAX_ENTITIES:
        raise ValueError(f"Select at most {MAX_ENTITIES} entities")
    result = []
    legacy_domains = {"light", "switch", "fan", "input_boolean", "scene", "script"}
    for entity in entities:
        entity_id = entity["entity_id"]
        domain = entity_id.split(".")[0]
        if entity.get("state") in ("unknown", "unavailable"):
            continue
        attrs = entity.get("attributes", {})
        features = attrs.get("supported_features", 0)
        features = features if type(features) is int else 0
        base = {"entity_id": entity_id, "name": entity["name"], "area": entity.get("area", ""),
                "aliases": entity.get("aliases", [])[:8], "state": entity.get("state", "")}

        def add(attribute, description, kind, options, service, field, unit="", scale=1):
            if not options or service not in services.get(domain, {}):
                return
            result.append({**base, "id": f"{entity_id}:{attribute}", "label": f"Set {entity['name']} {description}",
                "control": {"attribute": attribute, "description": description, "type": kind,
                            "options": options, "unit": unit},
                "service": f"{domain}.{service}", "arguments": {"entity_id": entity_id},
                "value_field": field, "value_scale": scale})

        if domain in legacy_domains:
            power = build_candidates([entity], tools)
            if domain == "fan":
                # FanEntityFeature.TURN_ON=32, TURN_OFF=16.
                power = [c for c in power if features & (32 if c["id"].endswith(":on") else 16)]
            for candidate in power:
                active = candidate["id"].endswith(":on")
                trigger = domain in ("scene", "script")
                candidate["control"] = {"attribute": "activation" if trigger else "power",
                    "description": "Activation" if trigger else "Power state",
                    "type": "choice" if trigger else "binary", "value": active,
                    "value_label": "Activate" if trigger else "On" if active else "Off"}
                result.append(candidate)
            # Use native power calls if the MCP server does not expose that operation.
            for operation in ("on", "off"):
                if domain in ("scene", "script") or any(c["id"] == f"{entity_id}:{operation}" for c in power):
                    continue
                if domain == "fan" and not features & (32 if operation == "on" else 16):
                    continue
                if f"turn_{operation}" in services.get(domain, {}):
                    result.append({**base, "id": f"{entity_id}:{operation}", "label": f"Turn {operation} {entity['name']}",
                        "control": {"attribute": "power", "description": "Power state", "type": "binary",
                                    "value": operation == "on", "value_label": operation.capitalize()},
                        "service": f"{domain}.turn_{operation}", "arguments": {"entity_id": entity_id}})
        if domain in ("climate", "media_player"):
            # ClimateEntityFeature and MediaPlayerEntityFeature power flags.
            bits = (256, 128) if domain == "climate" else (128, 256)
            for operation, bit in zip(("on", "off"), bits):
                if features & bit and f"turn_{operation}" in services.get(domain, {}):
                    result.append({**base, "id": f"{entity_id}:{operation}", "label": f"Turn {operation} {entity['name']}",
                        "control": {"attribute": "power", "description": "Power state", "type": "binary",
                                    "value": operation == "on", "value_label": operation.capitalize()},
                        "service": f"{domain}.turn_{operation}", "arguments": {"entity_id": entity_id}})

        if domain == "climate":
            unit = entity.get("temperature_unit", "")
            if features & 1:  # TARGET_TEMPERATURE (not the separate two-value range feature)
                add("temperature", "Target temperature", "score",
                    numeric_options(attrs.get("min_temp"), attrs.get("max_temp"), attrs.get("target_temp_step"), unit),
                    "set_temperature", "temperature", unit)
            add("hvac_mode", "Heating/cooling operating mode", "choice", choices(attrs.get("hvac_modes")), "set_hvac_mode", "hvac_mode")
            for name, feature, source in (("preset_mode", 16, "preset_modes"), ("fan_mode", 8, "fan_modes"), ("swing_mode", 32, "swing_modes")):
                if features & feature:
                    add(name, name.replace("_", " "), "choice", choices(attrs.get(source)), "set_" + name, name)
        elif domain == "light":
            modes = set(attrs.get("supported_color_modes") or [])
            if modes - {"onoff", "unknown"}:
                add("brightness", "Brightness", "score", numeric_options(0, 100, 1, "percent"), "turn_on", "brightness_pct", "percent")
        elif domain == "cover":
            if features & 4:  # CoverEntityFeature.SET_POSITION
                add("position", "Opening position (0 closed, 100 fully open)", "score",
                    numeric_options(0, 100, 1, "percent open"), "set_cover_position", "position", "percent open")
            else:
                for service, bit, value, label in (("open_cover", 1, 100.0, "Fully open"), ("close_cover", 2, 0.0, "Fully closed")):
                    if features & bit and service in services.get(domain, {}):
                        result.append({**base, "id": f"{entity_id}:{service}", "label": f"{label} {entity['name']}",
                            "control": {"attribute": "position", "description": "Opening position", "type": "choice",
                                        "value": value, "value_label": label},
                            "service": f"{domain}.{service}", "arguments": {"entity_id": entity_id}})
        elif domain == "fan":
            if features & 1:  # FanEntityFeature.SET_SPEED
                step = attrs.get("percentage_step")
                options = []
                if type(step) in (int, float) and math.isfinite(step) and 1 <= step <= 100:
                    count = round(100 / step)
                    if math.isclose(count * step, 100, abs_tol=.001):
                        options = [{"value": round(i * 100 / count), "label": f"{round(i * 100 / count)} percent"} for i in range(count + 1)]
                add("speed", "Fan speed", "score", options, "set_percentage", "percentage", "percent")
            if features & 8:  # PRESET_MODE
                add("preset_mode", "Fan preset", "choice", choices(attrs.get("preset_modes")), "set_preset_mode", "preset_mode")
        elif domain == "media_player":
            if features & 4:
                add("volume", "Volume", "score", numeric_options(0, 100, 1, "percent"), "volume_set", "volume_level", "percent", .01)
            if features & 2048:
                add("source", "Input source or listed TV channel", "choice", choices(attrs.get("source_list")), "select_source", "source")
            if features & 65536:
                add("sound_mode", "Sound mode", "choice", choices(attrs.get("sound_mode_list")), "select_sound_mode", "sound_mode")
            if features & 8:
                add("mute", "Muted state", "binary", [{"value": False, "label": "Unmuted"}, {"value": True, "label": "Muted"}], "volume_mute", "is_volume_muted")
        elif domain in ("select", "input_select"):
            add("option", "Selected option", "choice", choices(attrs.get("options")), "select_option", "option")
        elif domain in ("number", "input_number"):
            unit = attrs.get("unit_of_measurement", "")
            add("value", "Target value", "score", numeric_options(attrs.get("min"), attrs.get("max"), attrs.get("step"), unit), "set_value", "value", unit)
    if len(result) > MAX_CONTROLS or sum(len(c["control"].get("options", [None])) for c in result) > 4096:
        raise ValueError("Too many controls or supported values; select fewer entities")
    return result


def resolve_value(candidate, value):
    """Bind only a locally offered value to locally discovered service arguments."""
    control = candidate["control"]
    values = [o["value"] for o in control["options"]] if "options" in control else [control["value"]]
    match = next((v for v in values if type(value) is type(v) and value == v), None)
    if match is None:
        raise ValueError("Model selected an unsupported value")
    result = deepcopy(candidate)
    result["selected_value"] = match
    if "value_field" in result:
        result["arguments"][result["value_field"]] = match * result.get("value_scale", 1) if type(match) in (int, float) else match
        result["label"] += f" to {match} {control.get('unit', '')}".rstrip()
    return result
