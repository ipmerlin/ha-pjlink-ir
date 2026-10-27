"""Real HA entity states and services for optional Panasonic controls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.pjlink_ir.client import PJLinkError
from custom_components.pjlink_ir.const import DOMAIN
from custom_components.pjlink_ir.diagnostics import async_get_config_entry_diagnostics
from custom_components.pjlink_ir.panasonic import PanasonicCommandError, PanasonicConnectionError

VALUES = {
    "intake_temperature": 20, "exhaust_temperature": 40,
    "filter_hours": 142, "filter_rewinds": 2, "filter_since_rewind": 20, "filter_remaining": 1500,
    "volume": 30, "brightness": -1, "contrast": 32,
    "picture_mode": "cinema", "color_temperature": "default", "aspect": "16_9", "freeze": False,
}


@pytest.fixture
async def controls(hass):
    values = VALUES.copy()
    pjlink = {"POWR": "1", "LAMP": "4322 1", "ERST": "000000", "INPT": "31", "AVMT": "30", "INST": "11 31"}
    entry = MockConfigEntry(domain=DOMAIN, title="Cinema", data={
        "host": "192.0.2.20", "port": 4352, "manufacturer": "Panasonic", "model": "FW300NT",
        "password": "PRIVATE_PJLINK", "ir_command": "PRIVATE_IR",
    }, options={"panasonic_password": "PRIVATE_PANASONIC", "panasonic_username": "PRIVATE_USER"})
    entry.add_to_hass(hass)

    async def read(key):
        value = values[key]
        if isinstance(value, Exception):
            raise value
        return value

    async def control(key, value=None):
        if key in values:
            values[key] = int(value) if key in ("volume", "brightness", "contrast") else value

    reads = AsyncMock(side_effect=read)
    sends = AsyncMock(side_effect=control)
    with patch("custom_components.pjlink_ir.client.PJLinkClient.command", AsyncMock(
        side_effect=lambda key, value="?": pjlink[key]
    )), patch("custom_components.pjlink_ir.panasonic.PanasonicClient.daylight", AsyncMock(return_value="auto")), patch(
        "custom_components.pjlink_ir.panasonic.PanasonicClient.read", reads
    ), patch("custom_components.pjlink_ir.panasonic.PanasonicClient.control", sends):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield SimpleNamespace(entry=entry, coordinator=entry.runtime_data, values=values, pjlink=pjlink, reads=reads, sends=sends)
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def refresh(hass, controls):
    await controls.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_sensor_values_units_controls_and_one_device(hass, controls):
    assert hass.states.get("sensor.cinema_intake_air_temperature").state == "20"
    assert hass.states.get("sensor.cinema_intake_air_temperature").attributes["unit_of_measurement"] == "°C"
    assert hass.states.get("sensor.cinema_estimated_filter_time_remaining").state == "1500"
    assert hass.states.get("sensor.cinema_filter_operating_time").attributes["unit_of_measurement"] == "h"
    assert hass.states.get("sensor.cinema_filter_rewinds").state == "2"
    assert hass.states.get("number.cinema_volume").state == "30"
    assert hass.states.get("select.cinema_picture_mode").state == "cinema"
    assert hass.states.get("switch.cinema_freeze").state == "off"
    entities = er.async_entries_for_config_entry(er.async_get(hass), controls.entry.entry_id)
    assert len(entities) == 31
    assert len({entity.device_id for entity in entities}) == 1


@pytest.mark.parametrize("domain,service,name,data,key,value", [
    ("number", "set_value", "volume", {"value": 63}, "volume", 63),
    ("number", "set_value", "brightness", {"value": -32}, "brightness", -32),
    ("number", "set_value", "contrast", {"value": 0}, "contrast", 0),
    ("select", "select_option", "picture_mode", {"option": "dynamic"}, "picture_mode", "dynamic"),
    ("select", "select_option", "color_temperature", {"option": "high"}, "color_temperature", "high"),
    ("select", "select_option", "aspect_ratio", {"option": "4_3"}, "aspect", "4_3"),
    ("switch", "turn_on", "freeze", {}, "freeze", True),
    ("switch", "turn_off", "freeze", {}, "freeze", False),
    ("button", "press", "auto_setup", {}, "auto_setup", None),
    ("button", "press", "digital_zoom_in", {}, "zoom_in", None),
    ("button", "press", "digital_zoom_out", {}, "zoom_out", None),
])
async def test_services_send_once_without_ir(hass, controls, domain, service, name, data, key, value):
    controls.sends.reset_mock()
    with patch.object(controls.coordinator.wake, "send_ir", AsyncMock()) as ir:
        await hass.services.async_call(domain, service, {"entity_id": f"{domain}.cinema_{name}", **data}, blocking=True)
        await refresh(hass, controls)
        ir.assert_not_awaited()
    controls.sends.assert_awaited_once_with(key, value)
    if key in controls.values:
        state = hass.states.get(f"{domain}.cinema_{name}").state
        assert state == ("on" if value is True else "off" if value is False else str(value))


async def test_rejected_or_malformed_query_only_hides_affected_value(hass, controls):
    controls.values["intake_temperature"] = PanasonicCommandError("QTM:0", "ER401")
    controls.values["brightness"] = PJLinkError("Panasonic QVB: invalid response")
    await refresh(hass, controls)
    assert hass.states.get("sensor.cinema_intake_air_temperature").state == "unavailable"
    assert hass.states.get("number.cinema_brightness").state == "unavailable"
    assert hass.states.get("sensor.cinema_filter_operating_time").state == "142"
    assert hass.states.get("media_player.cinema").state == "on"
    assert "QTM:0" in controls.coordinator.data["query_errors"]["intake_temperature"]
    controls.values["intake_temperature"] = 0
    controls.values["brightness"] = 0
    await refresh(hass, controls)
    assert hass.states.get("sensor.cinema_intake_air_temperature").state == "0"
    assert hass.states.get("number.cinema_brightness").state == "0"


async def test_daylight_rejection_does_not_hide_other_panasonic_values(hass, controls):
    with patch.object(controls.coordinator.panasonic, "daylight", AsyncMock(
        side_effect=PanasonicCommandError("QVX:DLVI0", "ER401")
    )):
        await refresh(hass, controls)
    assert hass.states.get("select.cinema_daylight_view").state == "unavailable"
    assert hass.states.get("sensor.cinema_filter_operating_time").state == "142"
    assert hass.states.get("number.cinema_volume").state == "30"


async def test_transport_failure_stops_cycle_and_does_not_reuse_stale_values(hass, controls):
    controls.reads.reset_mock()
    controls.values["intake_temperature"] = PanasonicConnectionError("Panasonic unavailable")
    await refresh(hass, controls)
    controls.reads.assert_awaited_once_with("intake_temperature")
    assert hass.states.get("sensor.cinema_filter_operating_time").state == "unavailable"
    assert hass.states.get("number.cinema_volume").state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "on"


@pytest.mark.parametrize("power", ["0", "2", "3"])
async def test_transitions_do_not_poll_panasonic_or_dispatch_controls(hass, controls, power):
    controls.pjlink["POWR"] = power
    controls.reads.reset_mock()
    await refresh(hass, controls)
    controls.reads.assert_not_awaited()
    assert hass.states.get("switch.cinema_freeze").state == "unavailable"
    assert hass.states.get("sensor.cinema_filter_operating_time").state == "unavailable"
    assert hass.states.get("button.cinema_auto_setup").state == "unavailable"
    with pytest.raises(HomeAssistantError):
        await controls.coordinator.async_panasonic_control("freeze", True)
    controls.sends.assert_not_awaited()


async def test_uncertain_control_once_then_read_actual_state(hass, controls):
    async def lost_ack(key, value):
        controls.values[key] = value
        raise PanasonicConnectionError("Panasonic response lost")

    controls.sends.side_effect = lost_ack
    with pytest.raises(HomeAssistantError):
        await controls.coordinator.async_panasonic_control("freeze", True)
    await refresh(hass, controls)
    controls.sends.assert_awaited_once_with("freeze", True)
    assert hass.states.get("switch.cinema_freeze").state == "on"


async def test_diagnostics_include_values_but_not_credentials(hass, controls):
    report = await async_get_config_entry_diagnostics(hass, controls.entry)
    assert report["coordinator"]["state"]["panasonic"]["intake_temperature"] == 20
    assert report["summary"]["registry_entities"] == 31
    assert report["source_sha256"]["number.py"]
    assert "PRIVATE_" not in str(report)


async def test_polling_cycle_has_time_budget(hass, controls):
    # Force the budget context to expire at the first optional query boundary.
    import asyncio

    async def expired(key):
        await asyncio.sleep(1)

    with patch("custom_components.pjlink_ir.coordinator.PANASONIC_POLL_TIMEOUT", 0.01), patch.object(
        controls.coordinator.panasonic, "read", expired
    ):
        await refresh(hass, controls)
    assert "panasonic_poll" in controls.coordinator.data["query_errors"]
    assert hass.states.get("media_player.cinema").state == "on"
