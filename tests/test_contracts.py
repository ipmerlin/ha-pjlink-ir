"""Offline provider/flow contracts with mocked Home Assistant boundaries.

These supplement, but do not replace, tests/ha against the real HA runtime.
"""

import asyncio
from enum import IntFlag
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / ".test-deps").exists():
    sys.path.insert(0, str(ROOT / ".test-deps"))


class HomeAssistantError(Exception):
    pass


class Features(IntFlag):
    LEARN_COMMAND = 1


class Flow:
    def __init_subclass__(cls, **kwargs):
        pass


def load_modules():
    modules = {}
    for name in (
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.remote",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.selector",
    ):
        modules[name] = ModuleType(name)
    modules["homeassistant.components.remote"].RemoteEntityFeature = Features
    modules["homeassistant.config_entries"].ConfigFlow = Flow
    for name, value in {
        "CONF_HOST": "host",
        "CONF_PASSWORD": "password",
        "CONF_PORT": "port",
        "STATE_OFF": "off",
        "STATE_UNAVAILABLE": "unavailable",
        "STATE_UNKNOWN": "unknown",
    }.items():
        setattr(modules["homeassistant.const"], name, value)
    modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    selector = modules["homeassistant.helpers.selector"]
    for name in ("EntitySelector", "TextSelector", "SelectSelector"):
        setattr(selector, name, lambda config: lambda value: value)
        setattr(selector, name + "Config", lambda **kwargs: kwargs)
    selector.TextSelectorType = SimpleNamespace(PASSWORD="password")
    selector.SelectSelectorMode = SimpleNamespace(DROPDOWN="dropdown")
    package = ModuleType("pjlink_contract")
    package.__path__ = [str(ROOT / "custom_components" / "pjlink_ir")]
    modules["pjlink_contract"] = package
    with patch.dict(sys.modules, modules):
        remote = importlib.import_module("pjlink_contract.remote")
        flow = importlib.import_module("pjlink_contract.config_flow")
    return remote, flow


try:
    REMOTE, FLOW = load_modules()
except ModuleNotFoundError as error:
    if error.name not in ("voluptuous", "probatio"):
        raise
    REMOTE = FLOW = None

SETTINGS = {"remote_entity_id": "remote.any_vendor", "ir_device": "projector", "ir_command": "power_on"}


@unittest.skipIf(REMOTE is None, "Install voluptuous or probatio for offline flow contracts")
class ProviderContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = SimpleNamespace(
            states=SimpleNamespace(
                get=MagicMock(return_value=SimpleNamespace(state="on", attributes={"supported_features": 1}))
            ),
            services=SimpleNamespace(has_service=MagicMock(return_value=True), async_call=AsyncMock()),
        )

    async def test_any_remote_provider_send_once(self):
        await REMOTE.async_remote_command(self.hass, SETTINGS)
        self.hass.services.async_call.assert_awaited_once_with(
            "remote",
            "send_command",
            {"entity_id": "remote.any_vendor", "device": "projector", "command": ["power_on"], "num_repeats": 1},
            blocking=True,
        )

    async def test_generic_provider_without_namespace(self):
        await REMOTE.async_remote_command(self.hass, {**SETTINGS, "ir_device": ""})
        self.assertNotIn("device", self.hass.services.async_call.call_args.args[2])

    async def test_learning_standard_contract(self):
        await REMOTE.async_remote_command(self.hass, SETTINGS, learn=True)
        self.hass.services.async_call.assert_awaited_once_with(
            "remote",
            "learn_command",
            {
                "entity_id": "remote.any_vendor",
                "device": "projector",
                "command": ["power_on"],
                "command_type": "ir",
                "timeout": 30,
            },
            blocking=True,
        )

    async def test_no_learning_feature_no_service_dispatch(self):
        self.hass.states.get.return_value.attributes = {"supported_features": 0}
        with self.assertRaises(HomeAssistantError):
            await REMOTE.async_remote_command(self.hass, SETTINGS, learn=True)
        self.hass.services.async_call.assert_not_awaited()

    async def test_unavailable_remotes(self):
        for state in ("off", "unknown", "unavailable"):
            self.hass.states.get.return_value.state = state
            with self.assertRaises(HomeAssistantError):
                await REMOTE.async_remote_command(self.hass, SETTINGS)
        self.hass.states.get.return_value = None
        with self.assertRaises(HomeAssistantError):
            await REMOTE.async_remote_command(self.hass, SETTINGS)
        self.hass.services.async_call.assert_not_awaited()

    async def test_provider_errors_are_sanitized_and_not_retried(self):
        self.hass.services.async_call.side_effect = RuntimeError("SECRET RAW CODE")
        with self.assertRaises(HomeAssistantError) as ctx:
            await REMOTE.async_remote_command(self.hass, SETTINGS)
        self.assertNotIn("SECRET", str(ctx.exception))
        self.hass.services.async_call.assert_awaited_once()

    async def test_missing_service(self):
        self.hass.services.has_service.return_value = False
        with self.assertRaises(HomeAssistantError):
            await REMOTE.async_remote_command(self.hass, SETTINGS)
        self.hass.services.async_call.assert_not_awaited()


@unittest.skipIf(FLOW is None, "Install voluptuous or probatio for offline flow contracts")
class FlowContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.flow = FLOW.PJLinkIRConfigFlow()
        self.flow.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        for name in (
            "async_show_form",
            "async_show_progress",
            "async_show_progress_done",
            "async_create_entry",
            "async_update_reload_and_abort",
        ):
            setattr(self.flow, name, MagicMock(side_effect=lambda **kw: kw))
        self.flow.async_set_unique_id = AsyncMock()
        self.flow._abort_if_unique_id_configured = MagicMock()

    async def test_identification_to_ir_step(self):
        with patch.object(
            FLOW.PJLinkClient, "identify", AsyncMock(return_value={"manufacturer": "Panasonic", "model": "PT-Test"})
        ):
            result = await self.flow.async_step_user({"host": "192.0.2.20", "port": 4352})
        self.assertEqual(result["step_id"], "ir")
        self.assertEqual(result["description_placeholders"]["model"], "PT-Test")

    async def test_auth_error_does_not_save(self):
        with patch.object(FLOW.PJLinkClient, "identify", AsyncMock(side_effect=FLOW.AuthenticationError())):
            result = await self.flow.async_step_user({"host": "192.0.2.20", "port": 4352})
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.flow.async_create_entry.assert_not_called()

    async def test_learn_requires_explicit_start(self):
        self.flow._settings = {"host": "192.0.2.20"}
        with patch.object(FLOW, "check_remote"), patch.object(FLOW, "async_remote_command", AsyncMock()) as learn:
            result = await self.flow.async_step_ir({**SETTINGS, "command_setup": "learn", "wake_timeout": 90})
            self.assertEqual(result["step_id"], "learn_start")
            learn.assert_not_awaited()

    async def test_learning_progress_and_confirmation(self):
        self.flow._settings = SETTINGS.copy()
        with patch.object(FLOW, "async_remote_command", AsyncMock()) as learn:
            result = await self.flow.async_step_learn_start({})
            self.assertEqual(result["step_id"], "learn")
            await self.flow._learn_task
            result = await self.flow.async_step_learn()
            self.assertEqual(result["next_step_id"], "learn_confirm")
            learn.assert_awaited_once()
            await self.flow.async_step_learn_confirm()
            self.flow.async_create_entry.assert_not_called()

    async def test_provider_learning_failure_allows_retry(self):
        self.flow._settings = SETTINGS.copy()
        with patch.object(FLOW, "async_remote_command", AsyncMock(side_effect=RuntimeError())):
            await self.flow.async_step_learn_start({})
            await self.flow._learn_task
        result = await self.flow.async_step_learn()
        self.assertEqual(result["next_step_id"], "learn_failed")
        result = await self.flow.async_step_learn_failed({})
        self.assertEqual(result["step_id"], "learn_start")

    async def test_learning_cancellation_propagates(self):
        async def hang(*args, **kwargs):
            await asyncio.sleep(100)

        with patch.object(FLOW, "async_remote_command", hang):
            await self.flow.async_step_learn_start({})
            self.flow._learn_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await self.flow._learn_task
        self.flow.async_create_entry.assert_not_called()
