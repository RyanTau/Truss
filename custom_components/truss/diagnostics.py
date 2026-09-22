"""Diagnostics deliberately omit credentials, transcripts, and entity names."""
from .const import DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    config = coordinator.config
    return {"version": VERSION, "stt_mode": config["stt_mode"], "threshold": config["threshold"], "margin": config.get("margin", 0), "entity_count": len(config["entities"]), "mcp_tool_count": len(coordinator.tools), "active_streams": len(coordinator.websockets)}
