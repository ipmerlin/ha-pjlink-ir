"""Panasonic Daylight View modes with actual network readback."""

from homeassistant.components.select import SelectEntity

from .entity import PanasonicEntity, ProjectorDataEntity
from .panasonic import MODES
from .panasonic_features import SELECTS


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.panasonic is not None:
        async_add_entities([DaylightView(entry.runtime_data), *[
            PanasonicSelect(entry.runtime_data, key) for key in SELECTS
        ]])


class DaylightView(ProjectorDataEntity, SelectEntity):
    _data_key = "daylight_view"
    _attr_translation_key = "daylight_view"
    _attr_icon = "mdi:theme-light-dark"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_daylight_view"

    @property
    def current_option(self):
        return (self.coordinator.data or {}).get("daylight_view")

    @property
    def options(self):
        return ["off", "on"] if self.coordinator.panasonic.rear else list(MODES)

    async def async_select_option(self, option):
        await self.coordinator.async_daylight(option)


class PanasonicSelect(PanasonicEntity, SelectEntity):
    _attr_icon = "mdi:projector"

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._attr_options = list(SELECTS[key][2])

    @property
    def current_option(self):
        return self.value

    async def async_select_option(self, option):
        await self.coordinator.async_panasonic_control(self.key, option)
