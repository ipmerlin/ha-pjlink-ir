"""Read-only status refresh, including while the projector is offline."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import ProjectorEntity
from .panasonic_features import BUTTONS


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RefreshStatus(entry.runtime_data)])
    if entry.runtime_data.panasonic is not None:
        async_add_entities([PanasonicButton(entry.runtime_data, key) for key in BUTTONS])


class RefreshStatus(ProjectorEntity, ButtonEntity):
    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_refresh"

    @property
    def available(self):
        return True

    async def async_press(self):
        await self.coordinator.async_request_refresh()


class PanasonicButton(ProjectorEntity, ButtonEntity):
    _attr_icon = "mdi:projector"

    def __init__(self, coordinator, key):
        super().__init__(coordinator)
        self.key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_panasonic_{key}"
        self._attr_translation_key = key

    @property
    def available(self):
        return super().available and (self.coordinator.data or {}).get("power") == "1"

    async def async_press(self):
        await self.coordinator.async_panasonic_control(self.key)
