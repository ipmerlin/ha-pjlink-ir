"""Panasonic Daylight View modes with actual network readback."""

from homeassistant.components.select import SelectEntity

from .entity import ProjectorDataEntity
from .panasonic import MODES


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.panasonic is not None:
        async_add_entities([DaylightView(entry.runtime_data)])


class DaylightView(ProjectorDataEntity, SelectEntity):
    _data_key = "daylight_view"
    _attr_translation_key = "daylight_view"
    _attr_icon = "mdi:theme-light-dark"
    _attr_options = list(MODES)

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_daylight_view"

    @property
    def current_option(self):
        return (self.coordinator.data or {}).get("daylight_view")

    async def async_select_option(self, option):
        await self.coordinator.async_daylight(option)
