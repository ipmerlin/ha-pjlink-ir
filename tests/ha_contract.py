"""Actual HA lifecycle smoke test, without the Linux-only pytest runner plugin."""

import asyncio
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeassistant import auth, loader  # noqa: E402
from homeassistant.helpers import area_registry, device_registry, entity_registry  # noqa: E402
from homeassistant.config_entries import ConfigEntries, ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from custom_components.pjlink_ir.client import ConnectionUnavailable  # noqa: E402
from custom_components.pjlink_ir.diagnostics import async_get_config_entry_diagnostics  # noqa: E402

DATA = {
    "host": "192.0.2.20",
    "port": 4352,
    "manufacturer": "Panasonic",
    "model": "PT-Test",
    "remote_entity_id": "remote.contract",
    "ir_device": "projector",
    "ir_command": "power_on",
    "wake_timeout": 15,
}


async def main(config_dir):
    hass = HomeAssistant(config_dir)
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    device_registry.async_setup(hass)
    await area_registry.async_load(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    hass.auth = await auth.auth_manager_from_config(hass, [], [])
    await hass.config_entries.async_initialize()
    entry = ConfigEntry(
        domain="pjlink_ir",
        title="Cinema",
        data=DATA,
        options={},
        source="user",
        unique_id="192.0.2.20:4352",
        version=1,
        minor_version=1,
        discovery_keys={},
        subentries_data=[],
    )
    try:
        with patch("custom_components.pjlink_ir.coordinator.PJLinkClient.power", side_effect=ConnectionUnavailable()):
            await hass.config_entries.async_add(entry)
            await hass.async_block_till_done()
        players = hass.states.async_entity_ids("media_player")
        print("Player entities:", players)
        assert len(players) == 1
        player_id = players[0]
        assert hass.states.get(player_id).state == "unknown"
        assert hass.states.get(player_id).attributes["assumed_state"]
        assert len(hass.states.async_entity_ids("binary_sensor")) == 3
        print("PASS sleeping startup, media player and connectivity sensor")
        diagnostics = await async_get_config_entry_diagnostics(hass, entry)
        assert diagnostics["summary"] == {
            "registry_entities": 14,
            "active_entities": 14,
            "disabled_entities": 0,
            "devices": 1,
        }
        assert diagnostics["findings"] == []
        assert len([platform for platform in diagnostics["platforms"] if platform["belongs_to_entry"]]) == 7
        print("PASS read-only diagnostics: 14 entities linked to one device across seven platforms")
        hass.states.async_set("remote.contract", "on", {"supported_features": 1})
        send = AsyncMock()
        hass.services.async_register("remote", "send_command", send)
        entry.runtime_data.client.power = AsyncMock(side_effect=[ConnectionUnavailable(), "3", "3"])
        entry.runtime_data.client.command = AsyncMock(
            side_effect=lambda name, value="?": {"LAMP": "1200 1", "ERST": "000000"}[name]
        )
        entry.runtime_data.wake.interval = 0
        await hass.services.async_call("media_player", "turn_on", {"entity_id": player_id}, blocking=True)
        assert send.await_count == 1
        assert hass.states.get(player_id).state == "on"
        print("PASS generic remote wake through actual media_player.turn_on service")
        received = []
        values = {"POWR": "1", "NAME": "Cinema", "INF1": "Panasonic", "INF2": "PT-Test"}

        async def projector(reader, writer):
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

        async with await asyncio.start_server(projector, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            flow = await hass.config_entries.flow.async_init(
                "pjlink_ir", context={"source": "user"}, data={"host": "127.0.0.1", "port": port}
            )
        assert received == [b"%1POWR ?\r", b"%1NAME ?\r", b"%1INF1 ?\r", b"%1INF2 ?\r"]
        assert flow["step_id"] == "ir"
        assert flow["description_placeholders"]["model"] == "PT-Test"
        release = asyncio.Event()
        learned = asyncio.Event()

        async def learn(call):
            assert call.data["command"] == ["power_on"]
            assert call.data["timeout"] == 30
            learned.set()
            await release.wait()

        hass.services.async_register("remote", "learn_command", learn)
        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                "remote_entity_id": "remote.contract",
                "ir_device": "projector",
                "ir_command": "power_on",
                "command_setup": "learn",
                "wake_timeout": 30,
            },
        )
        assert flow["step_id"] == "learn_start"
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
        assert flow["type"] is FlowResultType.SHOW_PROGRESS
        await learned.wait()
        release.set()
        await hass.async_block_till_done()
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"])
        if flow["type"] is FlowResultType.SHOW_PROGRESS_DONE:
            flow = await hass.config_entries.flow.async_configure(flow["flow_id"])
        assert flow["step_id"] == "learn_confirm"
        assert len(hass.config_entries.async_entries("pjlink_ir")) == 1
        hass.config_entries.flow.async_abort(flow["flow_id"])
        print("PASS identification, standard IR learning progress and explicit confirmation")
        result = await hass.config_entries.flow.async_init(
            "pjlink_ir", context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        assert result["step_id"] == "ir"
        with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "remote_entity_id": "remote.contract",
                    "ir_device": "projector",
                    "ir_command": "on_new",
                    "command_setup": "saved",
                    "wake_timeout": 30,
                },
            )
        assert result["type"] is FlowResultType.ABORT
        assert entry.data["ir_command"] == "on_new"
        print("PASS real reconfigure flow updates the existing entry")
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(player_id).state == "unavailable"
        print("PASS unload lifecycle")
        daylight_entry = ConfigEntry(
            domain="pjlink_ir", title="Panasonic", data={**DATA, "model": "FW300NT"},
            options={}, source="user", unique_id="daylight-test", version=1, minor_version=1,
            discovery_keys={}, subentries_data=[],
        )
        mode = {"value": "auto"}

        async def daylight(value=None):
            if value is not None:
                mode["value"] = value
            return mode["value"]

        replies = {"POWR": "1", "LAMP": "123 1", "ERST": "000000", "INPT": "31", "AVMT": "30", "INST": "11 31"}
        feature_values = {
            "intake_temperature": 20, "exhaust_temperature": 40,
            "filter_hours": 142, "filter_rewinds": 2, "filter_since_rewind": 20, "filter_remaining": 1500,
            "volume": 30, "brightness": -1, "contrast": 32,
            "picture_mode": "cinema", "color_temperature": "default", "aspect": "16_9", "freeze": False,
        }

        async def control(key, value=None):
            if key in feature_values:
                feature_values[key] = int(value) if key in ("volume", "brightness", "contrast") else value

        with patch("custom_components.pjlink_ir.client.PJLinkClient.command", AsyncMock(
            side_effect=lambda name, value="?": replies[name]
        )), patch("custom_components.pjlink_ir.panasonic.PanasonicClient.daylight", AsyncMock(side_effect=daylight)) as lan, patch(
            "custom_components.pjlink_ir.panasonic.PanasonicClient.read", AsyncMock(side_effect=lambda key: feature_values[key])
        ), patch(
            "custom_components.pjlink_ir.panasonic.PanasonicClient.control", AsyncMock(side_effect=control)
        ):
            await hass.config_entries.async_add(daylight_entry)
            await hass.async_block_till_done()
            select_id = "select.panasonic_daylight_view"
            assert hass.states.get(select_id).state == "auto"
            assert len(entity_registry.async_entries_for_config_entry(
                entity_registry.async_get(hass), daylight_entry.entry_id
            )) == 32
            assert hass.states.get("sensor.panasonic_intake_air_temperature").state == "20"
            assert hass.states.get("sensor.panasonic_estimated_filter_time_remaining").state == "1500"
            for domain, service, name, data, expected in (
                ("number", "set_value", "volume", {"value": 63}, "63"),
                ("select", "select_option", "picture_mode", {"option": "dynamic"}, "dynamic"),
                ("switch", "turn_on", "freeze", {}, "on"),
            ):
                entity_id = f"{domain}.panasonic_{name}"
                await hass.services.async_call(domain, service, {"entity_id": entity_id, **data}, blocking=True)
                await daylight_entry.runtime_data.async_refresh()
                await hass.async_block_till_done()
                assert hass.states.get(entity_id).state == expected
            await hass.services.async_call("button", "press", {"entity_id": "button.panasonic_auto_setup"}, blocking=True)
            await hass.services.async_call("button", "press", {"entity_id": "button.panasonic_side_by_side"}, blocking=True)
            print("PASS Panasonic temperatures, filter, number/select/switch/button service readback")
            await hass.services.async_call("select", "select_option", {
                "entity_id": select_id, "option": "on",
            }, blocking=True)
            await daylight_entry.runtime_data.async_refresh()
            await hass.async_block_till_done()
            assert hass.states.get(select_id).state == "on"
            assert sum(call.args == ("on",) for call in lan.await_args_list) == 1
            replies["POWR"] = "2"
            lan.reset_mock()
            await daylight_entry.runtime_data.async_refresh()
            await hass.async_block_till_done()
            assert hass.states.get(select_id).state == "unavailable"
            lan.assert_not_awaited()
            options = await hass.config_entries.options.async_init(daylight_entry.entry_id)
            assert options["step_id"] == "init"
            with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload:
                options = await hass.config_entries.options.async_configure(options["flow_id"], {
                    "panasonic_enabled": True, "panasonic_port": 1024,
                    "panasonic_username": "admin1", "panasonic_password": "",
                })
                await hass.async_block_till_done()
                reload.assert_awaited_once_with(daylight_entry.entry_id)
            assert options["type"] is FlowResultType.CREATE_ENTRY
            assert daylight_entry.data["ir_command"] == DATA["ir_command"]
            assert await hass.config_entries.async_unload(daylight_entry.entry_id)
            await hass.async_block_till_done()
            assert hass.states.get(select_id).state == "unavailable"
            print("PASS Daylight View select, readback, cooling, options reload and unload")
    finally:
        await hass.async_stop(force=True)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix=".ha-check-", dir=ROOT) as config_dir:
        shutil.copytree(
            ROOT / "custom_components",
            Path(config_dir) / "custom_components",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        asyncio.run(main(config_dir))
