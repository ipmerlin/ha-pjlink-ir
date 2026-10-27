"""Read actual HA registries without exporting connection or IR configuration."""

import json
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pjlink_ir.client import ConnectionUnavailable
from custom_components.pjlink_ir.const import DOMAIN
from custom_components.pjlink_ir.diagnostics import async_get_config_entry_diagnostics

DATA = {
    "host": "192.0.2.99",
    "port": 4352,
    "password": "PRIVATE_PASSWORD_SENTINEL",
    "remote_entity_id": "remote.private_transmitter",
    "ir_device": "PRIVATE_IR_DEVICE_SENTINEL",
    "ir_command": "PRIVATE_IR_CODE_SENTINEL",
}


async def create_entry(hass, *, disable_new=False):
    entry = MockConfigEntry(
        domain=DOMAIN, title="Cinema", unique_id="192.0.2.99:4352", data=DATA, pref_disable_new_entities=disable_new
    )
    entry.add_to_hass(hass)
    with patch("custom_components.pjlink_ir.coordinator.PJLinkClient.power", side_effect=ConnectionUnavailable()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_diagnostics_reports_linked_entities_without_network_or_secrets(hass):
    entry = await create_entry(hass)
    entry.runtime_data.client.command = AsyncMock(side_effect=AssertionError("Diagnostics must not send commands"))
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["summary"] == {"registry_entities": 14, "active_entities": 14, "disabled_entities": 0, "devices": 1}
    assert report["findings"] == []
    assert all(entity["linked_to_entry_device"] for entity in report["registry_entities"])
    assert {platform["domain"] for platform in report["platforms"] if platform["belongs_to_entry"]} == {
        "media_player",
        "binary_sensor",
        "sensor",
        "switch",
        "button",
    }
    assert report["source_sha256"]["media_player.py"]
    serialized = json.dumps(report)
    for key in ("host", "password", "remote_entity_id", "ir_device", "ir_command"):
        assert DATA[key] not in serialized
    entry.runtime_data.client.command.assert_not_awaited()


async def test_diagnostics_distinguishes_disabled_entities(hass):
    entry = await create_entry(hass, disable_new=True)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["summary"]["registry_entities"] == 14
    assert report["summary"]["active_entities"] == 0
    assert report["summary"]["disabled_entities"] == 14
    assert "all_entities_disabled" in report["findings"]


async def test_diagnostics_reports_empty_entry_without_runtime(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Cinema", data=DATA)
    entry.add_to_hass(hass)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert not report["entry"]["has_runtime_data"]
    assert report["summary"]["registry_entities"] == 0
    assert "no_entities_for_entry" in report["findings"]
    assert "no_loaded_platforms_for_entry" in report["findings"]
