"""Resolve manual or Assist-based entity scope on the HA event loop."""
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.helpers import device_registry as dr, entity_registry as er
from .const import SUPPORTED_DOMAINS


def selected_entity_ids(hass, settings):
    # Existing installations keep their explicit allowlist.
    mode = settings.get("entity_mode", "manual")
    if mode == "manual":
        return list(settings.get("entities", []))
    if mode not in ("assist", "areas"):
        raise ValueError("Unknown entity selection mode")
    registry, devices = er.async_get(hass), dr.async_get(hass)
    selected_areas = set(settings.get("areas", []))
    result = []
    for state in hass.states.async_all():
        entity_id = state.entity_id
        if entity_id.split(".")[0] not in SUPPORTED_DOMAINS:
            continue
        if not async_should_expose(hass, "conversation", entity_id):
            continue
        if mode == "areas":
            record = registry.async_get(entity_id)
            area_id = record.area_id if record else None
            if not area_id and record and record.device_id:
                device = devices.async_get(record.device_id)
                area_id = device.area_id if device else None
            if area_id not in selected_areas:
                continue
        result.append(entity_id)
    return sorted(result)
