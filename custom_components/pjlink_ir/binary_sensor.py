"""Separate network connectivity from media player availability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .entity import LampEntity, ProjectorDataEntity, ProjectorEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([PJLinkConnectivity(coordinator), ProjectorProblem(coordinator)])
    added = set()

    @callback
    def discover_lamps():
        count = max(1, len((coordinator.data or {}).get("lamps") or []))
        new = [LampLit(coordinator, index) for index in range(count) if index not in added]
        added.update(range(count))
        if new:
            async_add_entities(new)

    discover_lamps()
    entry.async_on_unload(coordinator.async_add_listener(discover_lamps))


class PJLinkConnectivity(ProjectorEntity, BinarySensorEntity):
    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_available = True

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_connectivity"

    @property
    def is_on(self):
        return bool((self.coordinator.data or {}).get("connected"))


class LampLit(LampEntity, BinarySensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lightbulb-on-outline"

    def __init__(self, coordinator, index):
        super().__init__(coordinator, index)
        self._attr_translation_key = "lamp_lit" if index == 0 else "additional_lamp_lit"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_lamp_{index + 1}_lit"

    @property
    def is_on(self):
        return self.lamp["on"] if self.lamp is not None else None


class ProjectorProblem(ProjectorDataEntity, BinarySensorEntity):
    _data_key = "errors"
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_problem"

    @property
    def is_on(self):
        errors = (self.coordinator.data or {}).get("errors")
        return any(value != "ok" for value in errors.values()) if errors is not None else None
