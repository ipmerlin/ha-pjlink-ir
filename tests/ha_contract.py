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
        assert len([platform for platform in diagnostics["platforms"] if platform["belongs_to_entry"]]) == 5
        print("PASS read-only diagnostics: 14 entities linked to one device across five platforms")
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
