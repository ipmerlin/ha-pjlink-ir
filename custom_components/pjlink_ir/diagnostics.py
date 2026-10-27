"""Read-only entity-registration diagnostics without connection or IR settings."""

import hashlib
from pathlib import Path
import sys

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers import device_registry as dr, entity_platform, entity_registry as er
from homeassistant.loader import async_get_integration

from .const import DOMAIN


def _value(value):
    return getattr(value, "value", value)


def _source_files():
    """Hash installed code so incomplete updates can be identified without exporting it."""
    root = Path(__file__).parent
    names = (
        "__init__.py",
        "client.py",
        "coordinator.py",
        "entity.py",
        "media_player.py",
        "binary_sensor.py",
        "sensor.py",
        "switch.py",
        "button.py",
        "protocol.py",
        "panasonic.py",
        "select.py",
        "number.py",
        "panasonic_features.py",
        "manifest.json",
    )
    result = {}
    for name in names:
        path = root / name
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return result


async def async_get_config_entry_diagnostics(hass, entry):
    """Report actual registries/platforms, never passwords, host or IR command payloads."""
    integration = await async_get_integration(hass, DOMAIN)
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    device_ids = {device.id for device in devices}
    registry_entities = []
    for entity in entities:
        state = hass.states.get(entity.entity_id)
        registry_entities.append(
            {
                "entity_id": entity.entity_id,
                "domain": entity.domain,
                "device_id": entity.device_id,
                "linked_to_entry_device": entity.device_id in device_ids,
                "disabled_by": _value(entity.disabled_by),
                "hidden_by": _value(entity.hidden_by),
                "has_state": state is not None,
                "state": state.state if state is not None else None,
            }
        )
    platforms = []
    for platform in entity_platform.async_get_platforms(hass, DOMAIN):
        platform_entry = getattr(platform, "config_entry", None)
        platforms.append(
            {
                "domain": platform.domain,
                "belongs_to_entry": platform_entry is not None and platform_entry.entry_id == entry.entry_id,
                "active_entity_ids": sorted(platform.entities),
            }
        )
    coordinator = getattr(entry, "runtime_data", None)
    state_data = getattr(coordinator, "data", None) or {}
    active_count = sum(entity["has_state"] for entity in registry_entities)
    disabled_count = sum(entity["disabled_by"] is not None for entity in registry_entities)
    findings = []
    if not entities:
        findings.append("no_entities_for_entry")
    elif disabled_count == len(entities):
        findings.append("all_entities_disabled")
    elif active_count == 0:
        findings.append("registered_entities_missing_states")
    if not any(platform["belongs_to_entry"] for platform in platforms):
        findings.append("no_loaded_platforms_for_entry")
    if any(not entity["linked_to_entry_device"] for entity in registry_entities):
        findings.append("entities_not_linked_to_entry_devices")
    return {
        "home_assistant_version": HA_VERSION,
        "integration_version": integration.version,
        "entry": {
            "state": _value(entry.state),
            "disabled_by": _value(entry.disabled_by),
            "pref_disable_new_entities": entry.pref_disable_new_entities,
            "pref_disable_polling": entry.pref_disable_polling,
            "has_runtime_data": coordinator is not None,
        },
        "summary": {
            "registry_entities": len(entities),
            "active_entities": active_count,
            "disabled_entities": disabled_count,
            "devices": len(devices),
        },
        "findings": findings,
        "registry_entities": registry_entities,
        "devices": [
            {
                "device_id": device.id,
                "disabled_by": _value(device.disabled_by),
                "manufacturer": device.manufacturer,
                "model": device.model,
            }
            for device in devices
        ],
        "platforms": platforms,
        "coordinator": {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "state": {
                key: state_data.get(key)
                for key in (
                    "connected",
                    "power",
                    "source",
                    "muted",
                    "video_muted",
                    "inputs",
                    "lamps",
                    "errors",
                    "query_errors",
                    "daylight_view",
                    "panasonic",
                )
            },
        },
        "loaded_modules": {
            name: f"custom_components.{DOMAIN}.{name}" in sys.modules
            for name in ("media_player", "binary_sensor", "sensor", "switch", "button", "select", "number", "coordinator", "client", "panasonic")
        },
        "source_sha256": await hass.async_add_executor_job(_source_files),
    }
