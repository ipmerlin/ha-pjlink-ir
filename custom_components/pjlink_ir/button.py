"""Read-only status refresh, including while the projector is offline."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import ProjectorEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RefreshStatus(entry.runtime_data)])


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
