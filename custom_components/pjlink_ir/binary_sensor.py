"""Separate network connectivity from media player availability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import ProjectorEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PJLinkConnectivity(entry.runtime_data)])


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
