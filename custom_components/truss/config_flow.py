"""Native HA setup: detect MCP, configure engine/STT, choose entities."""
from __future__ import annotations
import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url, NoURLAvailableError
from .catalog import find_tool
from .const import DOMAIN, MAX_ENTITIES, SUPPORTED_DOMAINS
from .mcp import MCPClient, validate_url
from .selection import selected_entity_ids


async def check_mcp(hass, data):
    client = MCPClient(async_get_clientsession(hass), data["mcp_url"], data["mcp_token"])
    await client.initialize()
    tools = await client.list_tools()
    if not find_tool(tools, "HassTurnOn"):
        raise ValueError("The Assist MCP API must expose HassTurnOn with a name parameter")


async def check_engine(hass, data):
    validate_url(data["engine_url"])
    if data["stt_mode"] != "bundled":
        validate_url(data.get("stt_url", ""), websocket=True)
    async with async_get_clientsession(hass).get(data["engine_url"].rstrip("/") + "/health", headers={"Authorization": "Bearer " + data["engine_token"]}, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=15)) as response:
        response.raise_for_status()
        result = await response.json()
        if result.get("protocol") != "truss-v1" or not result.get("ready"):
            raise ValueError("Truss engine is not ready")
        if data["stt_mode"] == "bundled" and not result.get("bundled_stt"):
            raise ValueError("Enable bundled transcription in the Truss app")


def engine_schema(defaults):
    return vol.Schema({
        vol.Required("engine_url", default=defaults.get("engine_url", "")): str,
        vol.Required("engine_token", default=defaults.get("engine_token", "")): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        vol.Required("stt_mode", default=defaults.get("stt_mode", "bundled")): selector.SelectSelector(selector.SelectSelectorConfig(options=[{"value": "bundled", "label": "Run locally with Truss (sherpa-onnx)"}, {"value": "sherpa", "label": "External sherpa-onnx streaming server"}, {"value": "external", "label": "External Truss-protocol WebSocket"}])),
        vol.Optional("stt_url", default=defaults.get("stt_url", "")): str,
        vol.Optional("stt_token", default=defaults.get("stt_token", "")): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    })


def actions_schema(defaults):
    return vol.Schema({
        vol.Required("entity_mode", default=defaults.get("entity_mode", "manual" if "entities" in defaults else "assist")): selector.SelectSelector(selector.SelectSelectorConfig(options=[{"value": "assist", "label": "All supported entities exposed to Assist"}, {"value": "areas", "label": "Assist entities in selected rooms"}, {"value": "manual", "label": "Choose individual entities"}])),
        vol.Optional("areas", default=defaults.get("areas", [])): selector.AreaSelector(selector.AreaSelectorConfig(multiple=True)),
        vol.Optional("entities", default=defaults.get("entities", [])): selector.EntitySelector(selector.EntitySelectorConfig(domain=SUPPORTED_DOMAINS, multiple=True)),
        vol.Required("threshold", default=defaults.get("threshold", 0.80)): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=1)),
        vol.Required("margin", default=defaults.get("margin", 0.05)): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    })


class TrussConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.settings = {}

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        detected = bool(self.hass.config_entries.async_entries("mcp_server"))
        try:
            base_url = get_url(self.hass, prefer_external=False)
        except NoURLAvailableError:
            base_url = "http://homeassistant.local:8123"
        if user_input is not None:
            try:
                await check_mcp(self.hass, user_input)
            except Exception:
                errors["base"] = "cannot_connect_mcp"
            else:
                self.settings.update(user_input)
                return await self.async_step_engine()
        schema = vol.Schema({
            vol.Required("mcp_url", default=(user_input or {}).get("mcp_url", base_url.rstrip("/") + "/api/mcp")): str,
            vol.Required("mcp_token"): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors, description_placeholders={"detected": "Detected on this Home Assistant instance" if detected else "Not detected: add the MCP Server integration first"})

    async def async_step_engine(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await check_engine(self.hass, user_input)
            except Exception:
                errors["base"] = "cannot_connect_engine"
            else:
                user_input["engine_url"] = user_input["engine_url"].rstrip("/")
                self.settings.update(user_input)
                return await self.async_step_actions()
        return self.async_show_form(step_id="engine", data_schema=engine_schema(user_input or self.settings), errors=errors)

    async def async_step_actions(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not 1 <= len(selected_entity_ids(self.hass, user_input)) <= MAX_ENTITIES:
                errors["base"] = "entity_count"
            else:
                self.settings.update(user_input)
                return self.async_create_entry(title="Truss Live Voice", data=self.settings)
        return self.async_show_form(step_id="actions", data_schema=actions_schema(user_input or self.settings), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TrussOptionsFlow()


class TrussOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        defaults = {**self.config_entry.data, **self.config_entry.options}
        errors = {}
        form_defaults = {**defaults, **(user_input or {})}
        schema = dict(engine_schema(form_defaults).schema)
        schema.update(actions_schema(form_defaults).schema)
        schema.update({vol.Required("mcp_url", default=defaults["mcp_url"]): str,
                       vol.Required("mcp_token", default=defaults["mcp_token"]): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))})
        if user_input is not None:
            try:
                if not 1 <= len(selected_entity_ids(self.hass, user_input)) <= MAX_ENTITIES:
                    raise ValueError("entity_count")
                await check_mcp(self.hass, user_input)
                await check_engine(self.hass, user_input)
            except ValueError as error:
                errors["base"] = "entity_count" if str(error) == "entity_count" else "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                user_input["engine_url"] = user_input["engine_url"].rstrip("/")
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)
