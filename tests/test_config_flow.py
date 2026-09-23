"""Native flow branching with real schemas and small HA API doubles."""
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch
from support import integration


def load_flow():
    class Flow:
        def __init_subclass__(cls, **kwargs):
            pass
        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}
        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}
    class Selector:
        def __init__(self, config):
            self.config = config
        def __call__(self, value):
            return value
    names = ["homeassistant", "homeassistant.config_entries", "homeassistant.core",
             "homeassistant.helpers", "homeassistant.helpers.selector",
             "homeassistant.helpers.aiohttp_client", "homeassistant.helpers.network",
             "homeassistant.helpers.device_registry", "homeassistant.helpers.entity_registry",
             "homeassistant.components", "homeassistant.components.homeassistant",
             "homeassistant.components.homeassistant.exposed_entities"]
    modules = {name: types.ModuleType(name) for name in names}
    for name, module in modules.items():
        parent, _, child = name.rpartition(".")
        if parent in modules:
            setattr(modules[parent], child, module)
    modules["homeassistant.config_entries"].ConfigFlow = Flow
    modules["homeassistant.config_entries"].OptionsFlow = Flow
    modules["homeassistant.core"].callback = lambda f: f
    selectors = modules["homeassistant.helpers.selector"]
    for kind in ("Text", "Select", "Area", "Entity"):
        setattr(selectors, kind + "Selector", Selector)
        setattr(selectors, kind + "SelectorConfig", dict)
    selectors.TextSelectorType = types.SimpleNamespace(PASSWORD="password")
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = lambda hass: None
    modules["homeassistant.helpers.network"].get_url = lambda *args, **kw: "http://localhost:8123"
    modules["homeassistant.helpers.network"].NoURLAvailableError = ValueError
    modules["homeassistant.components.homeassistant.exposed_entities"].async_should_expose = lambda *args: True
    with patch.dict(sys.modules, modules):
        return integration("config_flow")


def fields(result):
    return {key.schema for key in result["data_schema"].schema}


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_only_shows_selected_picker(self):
        module = load_flow()
        for mode, picker in (("assist", set()), ("areas", {"areas"}), ("manual", {"entities"})):
            with self.subTest(mode=mode):
                flow = module.TrussConfigFlow()
                flow.hass = object()
                self.assertEqual(fields(await flow.async_step_selection()), {"entity_mode"})
                form = await flow.async_step_selection({"entity_mode": mode})
                self.assertEqual(fields(form), picker | {"threshold", "margin"})
                values = {"threshold": .8, "margin": .05, **{key: ["selected"] for key in picker}}
                with patch.object(module, "selected_entity_ids", return_value=["light.one"]):
                    result = await flow.async_step_actions(form["data_schema"](values))
                self.assertEqual(result["type"], "create_entry")
                self.assertEqual(result["data"]["entity_mode"], mode)
                if mode != "areas":
                    self.assertEqual(result["data"]["areas"], [])
                if mode != "manual":
                    self.assertEqual(result["data"]["entities"], [])

    async def test_options_switch_mode_clears_inactive_selection_and_preserves_settings(self):
        module = load_flow()
        defaults = {"mcp_url": "http://ha/api/mcp", "mcp_token": "ha-token",
                    "engine_url": "http://engine:10350", "engine_token": "engine-token",
                    "stt_mode": "bundled", "entity_mode": "manual", "entities": ["light.old"],
                    "areas": ["old-room"], "threshold": .9, "margin": .1}
        for mode, picker in (("assist", set()), ("areas", {"areas"}), ("manual", {"entities"})):
            flow = module.TrussOptionsFlow()
            flow.hass = object()
            flow.config_entry = types.SimpleNamespace(data=defaults, options={})
            first = await flow.async_step_init()
            self.assertFalse(fields(first) & {"areas", "entities", "threshold", "margin"})
            connection = first["data_schema"]({"entity_mode": mode})
            with patch.object(module, "check_mcp", AsyncMock()), patch.object(module, "check_engine", AsyncMock()):
                form = await flow.async_step_init(connection)
            self.assertEqual(fields(form), picker | {"threshold", "margin"})
            values = form["data_schema"]({key: ["new"] for key in picker})
            with patch.object(module, "selected_entity_ids", return_value=[]):
                retry = await flow.async_step_actions(values)
            self.assertEqual(retry["errors"], {"base": "entity_count"})
            self.assertEqual(fields(retry), fields(form))
            with patch.object(module, "selected_entity_ids", return_value=["light.one"]):
                result = await flow.async_step_actions(values)
            saved = result["data"]
            self.assertEqual(saved["threshold"], .9)
            self.assertEqual(saved["mcp_token"], "ha-token")
            self.assertEqual(saved["areas"], ["new"] if mode == "areas" else [])
            self.assertEqual(saved["entities"], ["new"] if mode == "manual" else [])

    async def test_legacy_manual_defaults(self):
        module = load_flow()
        schema = module.selection_schema({"entities": ["light.one"]})
        self.assertEqual(schema({})["entity_mode"], "manual")
