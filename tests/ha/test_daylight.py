"""Actual HA select lifecycle, options and isolation from PJLink/IR."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.pjlink_ir.client import PJLinkError
from custom_components.pjlink_ir.const import DOMAIN
from custom_components.pjlink_ir.diagnostics import async_get_config_entry_diagnostics


@pytest.fixture
async def daylight(hass):
    values = {"POWR": "1", "LAMP": "1234 1", "ERST": "000000", "INPT": "31", "AVMT": "30", "INST": "11 31"}
    entry = MockConfigEntry(domain=DOMAIN, title="Cinema", data={
        "host": "192.0.2.20", "port": 4352, "manufacturer": "Panasonic", "model": "FW300NT",
        "password": "PRIVATE_PASSWORD",
    })
    entry.add_to_hass(hass)
    current = {"mode": "auto", "error": None}

    async def mode(value=None):
        if current["error"]:
            raise current["error"]
        if value is not None:
            current["mode"] = value
        return current["mode"]

    command = AsyncMock(side_effect=lambda name, value="?": values[name])
    panasonic = AsyncMock(side_effect=mode)
    with patch("custom_components.pjlink_ir.client.PJLinkClient.command", command), patch(
        "custom_components.pjlink_ir.panasonic.PanasonicClient.daylight", panasonic
    ), patch(
        "custom_components.pjlink_ir.panasonic.PanasonicClient.read", AsyncMock(return_value=None)
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, values, current, panasonic
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_select_modes_readback_and_diagnostics(hass, daylight):
    entry, values, current, panasonic = daylight
    state = hass.states.get("select.cinema_daylight_view")
    assert state.state == "auto"
    assert state.attributes["options"] == ["off", "auto", "on"]
    assert len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 31
    panasonic.reset_mock()
    for mode in ("on", "off", "auto"):
        await hass.services.async_call("select", "select_option", {
            "entity_id": state.entity_id, "option": mode,
        }, blocking=True)
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(state.entity_id).state == mode
        assert sum(call.args == (mode,) for call in panasonic.await_args_list) == 1
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["coordinator"]["state"]["daylight_view"] == "auto"
    assert "PRIVATE_PASSWORD" not in str(diagnostics)
    assert diagnostics["findings"] == []


async def test_failure_isolated_and_recovers(hass, daylight):
    entry, values, current, panasonic = daylight
    current["error"] = PJLinkError("Panasonic unavailable")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.cinema_daylight_view").state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "on"
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "1234"
    current["error"] = None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.cinema_daylight_view").state == "auto"


async def test_rear_projection_exposes_only_valid_options(hass, daylight):
    entry, values, current, panasonic = daylight
    entry.runtime_data.panasonic.rear = True
    current["mode"] = "on"
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get("select.cinema_daylight_view")
    assert state.state == "on"
    assert state.attributes["options"] == ["off", "on"]


@pytest.mark.parametrize("power", ["0", "2", "3"])
async def test_no_panasonic_query_or_control_during_transitions(hass, daylight, power):
    entry, values, current, panasonic = daylight
    panasonic.reset_mock()
    values["POWR"] = power
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.cinema_daylight_view").state == "unavailable"
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.async_daylight("on")
    panasonic.assert_not_awaited()


async def test_uncertain_set_once_readback_without_ir(hass, daylight):
    entry, values, current, panasonic = daylight
    calls = []

    async def lost_ack(mode=None):
        calls.append(mode)
        if mode is not None:
            current["mode"] = mode
            raise PJLinkError("Panasonic response lost")
        return current["mode"]

    panasonic.side_effect = lost_ack
    with patch.object(entry.runtime_data.wake, "send_ir", AsyncMock()) as ir:
        with pytest.raises(HomeAssistantError):
            await entry.runtime_data.async_daylight("on")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        ir.assert_not_awaited()
    assert calls.count("on") == 1
    assert hass.states.get("select.cinema_daylight_view").state == "on"


async def test_options_preserve_ir_and_reload(hass, daylight):
    entry, values, current, panasonic = daylight
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload:
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "panasonic_enabled": False, "panasonic_port": 1025,
            "panasonic_username": "admin2", "panasonic_password": "PRIVATE_OTHER",
        })
        await hass.async_block_till_done()
        reload.assert_awaited_once_with(entry.entry_id)
    assert result["type"] == "create_entry"
    assert entry.data["model"] == "FW300NT"
    assert entry.options["panasonic_enabled"] is False


async def test_disable_removes_select_only(hass, daylight):
    entry, values, current, panasonic = daylight
    await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(entry, options={"panasonic_enabled": False})
    panasonic.reset_mock()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.panasonic is None
    assert hass.states.get("select.cinema_daylight_view").state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "on"
    panasonic.assert_not_awaited()
