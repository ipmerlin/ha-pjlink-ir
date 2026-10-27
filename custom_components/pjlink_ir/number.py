"""Validated Panasonic volume and picture adjustments with readback."""

from homeassistant.components.number import NumberEntity, NumberMode

from .entity import PanasonicEntity
from .panasonic_features import NUMBERS


async def async_setup_entry(hass, entry, async_add_entities):
    if entry.runtime_data.panasonic is not None:
        async_add_entities([PanasonicNumber(entry.runtime_data, key) for key in NUMBERS])


class PanasonicNumber(PanasonicEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _attr_icon = "mdi:tune"

    def __init__(self, coordinator, key):
        super().__init__(coordinator, key)
        self._attr_native_min_value, self._attr_native_max_value = NUMBERS[key][2:]
        if key == "volume":
            self._attr_icon = "mdi:volume-high"

    @property
    def native_value(self):
        return self.value

    async def async_set_native_value(self, value):
        await self.coordinator.async_panasonic_control(self.key, value)
