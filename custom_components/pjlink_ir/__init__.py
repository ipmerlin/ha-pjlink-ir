"""PJLink with IR wake integration."""

from homeassistant.const import Platform

from .coordinator import ProjectorCoordinator

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.SELECT]


async def async_setup_entry(hass, entry):
    coordinator = ProjectorCoordinator(hass, entry)
    # Do not block startup on the sleeping projector or require network access.
    entry.runtime_data = coordinator
    await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
