"""Real HA states, services, optional replies and dynamic multi-lamp entities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.pjlink_ir.client import CommandError, ConnectionUnavailable
from custom_components.pjlink_ir.const import DOMAIN


@pytest.fixture
async def projector(hass):
    values = {"POWR": "1", "LAMP": "1234 1", "ERST": "000000", "INPT": "31", "AVMT": "30", "INST": "11 21 31"}
    calls = []

    async def command(client, name, value="?"):
        calls.append((name, value))
        if value != "?":
            error = values.get("send_error")
            if error:
                raise error
            if name == "AVMT":
                values["AVMT"] = value
            return "OK"
        reply = values[name]
        if isinstance(reply, Exception):
            raise reply
        return reply

    entry = MockConfigEntry(
        domain=DOMAIN, title="Cinema", unique_id="192.0.2.20:4352", data={"host": "192.0.2.20", "port": 4352}
    )
    entry.add_to_hass(hass)
    with patch("custom_components.pjlink_ir.client.PJLinkClient.command", command):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield SimpleNamespace(entry=entry, coordinator=entry.runtime_data, values=values, calls=calls)
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def refresh(hass, projector):
    await projector.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_lamp_hours_and_all_entities_link_to_one_device(hass, projector):
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "1234"
    assert hass.states.get("sensor.cinema_lamp_operating_time").attributes["unit_of_measurement"] == "h"
    assert hass.states.get("sensor.cinema_lamp_operating_time").attributes["state_class"] == "total_increasing"
    assert hass.states.get("binary_sensor.cinema_lamp_lit").state == "on"
    assert hass.states.get("sensor.cinema_power_phase").state == "on"
    assert hass.states.get("binary_sensor.cinema_problem").state == "off"
    assert hass.states.get("switch.cinema_av_mute").state == "off"
    entities = er.async_entries_for_config_entry(er.async_get(hass), projector.entry.entry_id)
    assert len(entities) == 14
    assert len({entity.device_id for entity in entities}) == 1
    assert all(entity.device_id for entity in entities)


async def test_warnings_errors_and_clear(hass, projector):
    projector.values["ERST"] = "102010"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_fan_status").state == "warning"
    assert hass.states.get("sensor.cinema_temperature_status").state == "error"
    assert hass.states.get("sensor.cinema_filter_status").state == "warning"
    assert hass.states.get("binary_sensor.cinema_problem").state == "on"
    projector.values["ERST"] = "000000"
    await refresh(hass, projector)
    assert hass.states.get("binary_sensor.cinema_problem").state == "off"


@pytest.mark.parametrize("power,phase", [("0", "standby"), ("2", "cooling"), ("3", "warming")])
async def test_diagnostics_during_power_transitions_without_control_commands(hass, projector, power, phase):
    projector.calls.clear()
    projector.values.update(POWR=power, LAMP="1234 0")
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_power_phase").state == phase
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "1234"
    assert hass.states.get("binary_sensor.cinema_lamp_lit").state == "off"
    assert hass.states.get("switch.cinema_av_mute").state == "unavailable"
    assert projector.calls == [("POWR", "?"), ("LAMP", "?"), ("ERST", "?")]


async def test_sleep_clears_current_telemetry_and_refresh_never_sends_ir(hass, projector):
    projector.values["POWR"] = ConnectionUnavailable()
    await refresh(hass, projector)
    for name in (
        "sensor.cinema_lamp_operating_time",
        "binary_sensor.cinema_lamp_lit",
        "binary_sensor.cinema_problem",
        "sensor.cinema_temperature_status",
        "switch.cinema_av_mute",
    ):
        assert hass.states.get(name).state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "unknown"
    assert hass.states.get("binary_sensor.cinema_pjlink_connection").state == "off"
    ir = AsyncMock()
    with patch.object(projector.coordinator.wake, "send_ir", ir):
        await hass.services.async_call("button", "press", {"entity_id": "button.cinema_refresh_status"}, blocking=True)
    ir.assert_not_awaited()
    assert all(value == "?" for name, value in projector.calls)


async def test_unsupported_lamp_does_not_break_other_entities_or_repeat_query(hass, projector):
    projector.values["LAMP"] = CommandError("ERR1")
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "on"
    assert hass.states.get("binary_sensor.cinema_problem").state == "off"
    projector.calls.clear()
    await refresh(hass, projector)
    assert ("LAMP", "?") not in projector.calls
    assert ("ERST", "?") in projector.calls


async def test_malformed_lamp_recovers_without_affecting_power(hass, projector):
    projector.values["LAMP"] = "broken 1"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "unavailable"
    assert hass.states.get("media_player.cinema").state == "on"
    projector.values["LAMP"] = "0 1"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "0"


async def test_invalid_error_status_never_reports_healthy(hass, projector):
    projector.values["ERST"] = "invalid"
    await refresh(hass, projector)
    assert hass.states.get("binary_sensor.cinema_problem").state == "unavailable"
    assert hass.states.get("sensor.cinema_temperature_status").state == "unavailable"
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "1234"


async def test_temporary_rejection_is_retried_on_next_poll(hass, projector):
    projector.values["LAMP"] = CommandError("ERR3")
    await refresh(hass, projector)
    projector.values["LAMP"] = "1235 1"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_operating_time").state == "1235"


async def test_av_mute_dispatches_one_network_command_and_reads_back(hass, projector):
    projector.calls.clear()
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.cinema_av_mute"}, blocking=True)
    await refresh(hass, projector)
    assert hass.states.get("switch.cinema_av_mute").state == "on"
    assert projector.calls.count(("AVMT", "31")) == 1
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.cinema_av_mute"}, blocking=True)
    await refresh(hass, projector)
    assert hass.states.get("switch.cinema_av_mute").state == "off"
    assert projector.calls.count(("AVMT", "30")) == 1


async def test_av_mute_failure_is_not_retried(hass, projector):
    projector.calls.clear()
    projector.values["send_error"] = CommandError("ERR3")
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.cinema_av_mute"}, blocking=True)
    assert projector.calls.count(("AVMT", "31")) == 1
    assert hass.states.get("switch.cinema_av_mute").state == "off"


async def test_multiple_lamps_discovered_after_sleep_without_duplicates(hass, projector):
    projector.values["LAMP"] = "1234 1 500 0"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_2_operating_time").state == "500"
    assert hass.states.get("binary_sensor.cinema_lamp_2_lit").state == "off"
    projector.values["LAMP"] = "1234 1"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_2_operating_time").state == "unavailable"
    projector.values["LAMP"] = "1234 1 501 1"
    await refresh(hass, projector)
    assert hass.states.get("sensor.cinema_lamp_2_operating_time").state == "501"
    entities = er.async_entries_for_config_entry(er.async_get(hass), projector.entry.entry_id)
    assert len(entities) == 16
