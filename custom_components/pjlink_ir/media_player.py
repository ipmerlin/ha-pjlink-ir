"""PJLink media player with a callable IR wake path."""

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .client import PJLinkError
from .entity import ProjectorEntity

SOURCE_TYPES = {"1": "RGB", "2": "VIDEO", "3": "DIGITAL", "4": "STORAGE", "5": "NETWORK"}


def source_name(code):
    return f"{SOURCE_TYPES[code[0]]} {code[1]}"


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PJLinkMediaPlayer(entry.runtime_data)])


class PJLinkMediaPlayer(ProjectorEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.PROJECTOR
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_player"

    @property
    def available(self):
        # A sleeping network interface must not disable the media-player service.
        return True

    @property
    def assumed_state(self):
        # Show explicit On/Off actions when network feedback is absent.
        return not (self.coordinator.data or {}).get("connected", False)

    @property
    def state(self):
        data = self.coordinator.data or {}
        # Offline is ambiguous: sleep and a disconnected cable look identical.
        if not data.get("connected"):
            return None
        return MediaPlayerState.ON if data["power"] in ("1", "3") else MediaPlayerState.OFF

    @property
    def source_list(self):
        return [source_name(code) for code in (self.coordinator.data or {}).get("inputs", [])]

    @property
    def source(self):
        code = (self.coordinator.data or {}).get("source")
        return source_name(code) if code else None

    @property
    def is_volume_muted(self):
        return (self.coordinator.data or {}).get("muted")

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "pjlink_connected": data.get("connected", False),
            "power_phase": {"0": "standby", "1": "on", "2": "cooling", "3": "warming"}.get(
                data.get("power"), "unknown"
            ),
            "last_error": data.get("error"),
        }

    async def async_turn_on(self):
        try:
            await self.coordinator.wake.turn_on()
        except PJLinkError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.coordinator.async_request_refresh()

    async def _command(self, command, value):
        try:
            async with self.coordinator.wake.lock:
                await self.coordinator.client.command(command, value)
        except PJLinkError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self):
        await self._command("POWR", "0")

    async def async_select_source(self, source):
        mapping = {source_name(code): code for code in (self.coordinator.data or {}).get("inputs", [])}
        if source not in mapping:
            raise ServiceValidationError("Input is unavailable; wait for the projector to power on")
        await self._command("INPT", mapping[source])

    async def async_mute_volume(self, mute):
        await self._command("AVMT", "21" if mute else "20")
