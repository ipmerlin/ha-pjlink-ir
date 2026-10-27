"""Standard PJLink AV mute (30/31); does not power off the projector."""

from homeassistant.components.switch import SwitchEntity

from .entity import PanasonicEntity, ProjectorDataEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([AVMute(entry.runtime_data)])
    if entry.runtime_data.panasonic is not None:
        async_add_entities([Freeze(entry.runtime_data, "freeze")])


class AVMute(ProjectorDataEntity, SwitchEntity):
    _data_key = "video_muted"
    _attr_translation_key = "av_mute"
    _attr_icon = "mdi:projector-off"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_av_mute"

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get("video_muted")

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_command("AVMT", "31")

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_command("AVMT", "30")


class Freeze(PanasonicEntity, SwitchEntity):
    _attr_icon = "mdi:pause-box-outline"

    @property
    def is_on(self):
        return self.value

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_panasonic_control("freeze", True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_panasonic_control("freeze", False)
