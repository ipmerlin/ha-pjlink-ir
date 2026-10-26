"""Use Home Assistant remote services without reading private IR storage."""

import asyncio

from homeassistant.components.remote import RemoteEntityFeature
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_IR_COMMAND, CONF_IR_DEVICE, CONF_REMOTE


def check_remote(hass, settings, *, learn=False):
    """Reject absent, disabled and unavailable remotes before service dispatch."""
    state = hass.states.get(settings[CONF_REMOTE])
    if state is None or state.state in (STATE_OFF, STATE_UNAVAILABLE, STATE_UNKNOWN):
        raise HomeAssistantError("IR remote is missing, off or unavailable")
    if learn and not int(state.attributes.get("supported_features", 0)) & RemoteEntityFeature.LEARN_COMMAND:
        raise HomeAssistantError("This remote does not support command learning")
    service = "learn_command" if learn else "send_command"
    if not hass.services.has_service("remote", service):
        raise HomeAssistantError("Remote service is unavailable")


async def async_remote_command(hass, settings, *, learn=False):
    check_remote(hass, settings, learn=learn)
    data = {
        "entity_id": settings[CONF_REMOTE],
        "command": [settings[CONF_IR_COMMAND]],
    }
    if settings.get(CONF_IR_DEVICE):
        data["device"] = settings[CONF_IR_DEVICE]
    if learn:
        data["command_type"] = "ir"
        data["timeout"] = 30
    else:
        data["num_repeats"] = 1
    # Broadlink can swallow learning failures: the flow asks for explicit confirmation.
    try:
        async with asyncio.timeout(45 if learn else 15):
            await hass.services.async_call("remote", "learn_command" if learn else "send_command", data, blocking=True)
    except Exception:
        # Third-party errors can contain raw codes, credentials or addresses.
        raise HomeAssistantError("IR request failed; check the selected transmitter integration") from None
