"""Integration lifecycle and UI tests against Home Assistant itself."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pjlink_ir.client import AuthenticationError, ConnectionUnavailable
from custom_components.pjlink_ir.const import DOMAIN

DATA = {
    "host": "192.0.2.20",
    "port": 4352,
    "manufacturer": "Panasonic",
    "model": "PT-Test",
    "remote_entity_id": "remote.test_ir",
    "ir_device": "panasonic",
    "ir_command": "power_on",
    "wake_timeout": 15,
}


async def setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Cinema", unique_id="192.0.2.20:4352", data=DATA)
    entry.add_to_hass(hass)
    with patch("custom_components.pjlink_ir.coordinator.PJLinkClient.power", side_effect=ConnectionUnavailable()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_sleeping_startup_and_unload(hass):
    entry = await setup(hass)
    assert hass.states.get("media_player.cinema").state == STATE_UNKNOWN
    assert hass.states.get("media_player.cinema").attributes["assumed_state"]
    assert hass.states.get("binary_sensor.cinema_pjlink_connection").state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("media_player.cinema").state == "unavailable"


async def test_sleeping_entity_can_send_generic_ir(hass):
    entry = await setup(hass)
    # Register after setup to avoid collision with the remote platform.
    send = AsyncMock()
    hass.states.async_set("remote.test_ir", "on", {"supported_features": 0})
    hass.services.async_register("remote", "send_command", send)
    coordinator = entry.runtime_data
    coordinator.client.power = AsyncMock(side_effect=[ConnectionUnavailable(), "3", "3"])
    coordinator.client.command = AsyncMock(
        side_effect=lambda name, value="?": {"LAMP": "1200 1", "ERST": "000000"}[name]
    )
    coordinator.wake.interval = 0
    await hass.services.async_call("media_player", "turn_on", {"entity_id": "media_player.cinema"}, blocking=True)
    assert send.await_count == 1
    assert send.call_args.args[0].data["num_repeats"] == 1
    assert hass.states.get("media_player.cinema").state == "on"


@pytest.mark.parametrize("state", [None, "off", "unavailable", "unknown"])
async def test_missing_or_unavailable_ir_fails(hass, state):
    entry = await setup(hass)
    if state:
        hass.states.async_set("remote.test_ir", state)
    send = AsyncMock()
    hass.services.async_register("remote", "send_command", send)
    entry.runtime_data.client.power = AsyncMock(side_effect=ConnectionUnavailable())
    from homeassistant.exceptions import HomeAssistantError

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("media_player", "turn_on", {"entity_id": "media_player.cinema"}, blocking=True)
    send.assert_not_awaited()


async def test_flow_identifies_model_and_selects_any_remote(hass):
    with patch(
        "custom_components.pjlink_ir.config_flow.PJLinkClient.identify",
        return_value={"name": "Cinema", "manufacturer": "Panasonic", "model": "PT-Test"},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": DATA["host"], "port": 4352}
        )
    assert result["step_id"] == "ir"
    assert result["description_placeholders"]["model"] == "PT-Test"
    hass.states.async_set("remote.any_vendor", "on")
    hass.services.async_register("remote", "send_command", AsyncMock())
    with patch("custom_components.pjlink_ir.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "remote_entity_id": "remote.any_vendor",
                "ir_device": "",
                "ir_command": "power_on",
                "command_setup": "saved",
                "wake_timeout": 90,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["model"] == "PT-Test"


async def test_flow_auth_failure(hass):
    with patch("custom_components.pjlink_ir.config_flow.PJLinkClient.identify", side_effect=AuthenticationError()):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": DATA["host"], "port": 4352}
        )
    assert result["errors"]["base"] == "invalid_auth"


async def test_flow_identifies_model_over_real_tcp(hass, socket_enabled):
    """Exercise config flow -> identify -> command validation -> actual TCP."""
    received = []
    values = {"POWR": "1", "NAME": "Cinema", "INF1": "Panasonic", "INF2": "PT-Test"}

    async def handle(reader, writer):
        try:
            writer.write(b"PJLINK 0\r")
            await writer.drain()
            request = await reader.readuntil(b"\r")
            received.append(request)
            name = request[2:6].decode("ascii")
            writer.write(f"%1{name}={values[name]}\r".encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async with await asyncio.start_server(handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": "127.0.0.1", "port": port}
        )
    assert result["step_id"] == "ir"
    assert result["description_placeholders"] == {"manufacturer": "Panasonic", "model": "PT-Test"}
    assert received == [b"%1POWR ?\r", b"%1NAME ?\r", b"%1INF1 ?\r", b"%1INF2 ?\r"]
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_learning_progress_then_explicit_confirmation(hass):
    with patch("custom_components.pjlink_ir.config_flow.PJLinkClient.identify", return_value={"model": "PT-Test"}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={"host": DATA["host"], "port": 4352}
        )
    from homeassistant.components.remote import RemoteEntityFeature

    hass.states.async_set("remote.any_vendor", "on", {"supported_features": int(RemoteEntityFeature.LEARN_COMMAND)})
    learned = asyncio.Event()
    release = asyncio.Event()

    async def learn(call):
        assert call.data["command_type"] == "ir"
        assert call.data["command"] == ["power_on"]
        learned.set()
        await release.wait()

    hass.services.async_register("remote", "learn_command", learn)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "remote_entity_id": "remote.any_vendor",
            "ir_device": "projector",
            "ir_command": "power_on",
            "command_setup": "learn",
            "wake_timeout": 90,
        },
    )
    assert result["step_id"] == "learn_start"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await learned.wait()
    release.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    if result["type"] is FlowResultType.SHOW_PROGRESS_DONE:
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "learn_confirm"
    assert not hass.config_entries.async_entries(DOMAIN)
    with patch("custom_components.pjlink_ir.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"confirmed": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reconfigure_updates_existing_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Cinema", unique_id="192.0.2.20:4352", data=DATA)
    entry.add_to_hass(hass)
    hass.states.async_set("remote.any_vendor", "on")
    hass.services.async_register("remote", "send_command", AsyncMock())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "remote_entity_id": "remote.any_vendor",
                "ir_device": "",
                "ir_command": "on",
                "command_setup": "saved",
                "wake_timeout": 60,
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert entry.data["remote_entity_id"] == "remote.any_vendor"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
