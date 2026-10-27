"""Poll real PJLink state while leaving IR wake callable during sleep."""

from datetime import timedelta
import logging
import re

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import CommandError, PJLinkClient, PJLinkError
from .const import CONF_WAKE_TIMEOUT, DEFAULT_WAKE_TIMEOUT, DOMAIN
from .remote import async_remote_command
from .protocol import parse_errors, parse_lamps
from .panasonic import PanasonicClient, supports_daylight
from .wake import WakeController

_LOGGER = logging.getLogger(__name__)


class ProjectorCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=timedelta(seconds=30))
        self.entry = entry
        self.settings = {**entry.data, **entry.options}
        self.client = PJLinkClient(
            self.settings[CONF_HOST], self.settings[CONF_PORT], self.settings.get(CONF_PASSWORD, "")
        )
        self.wake = WakeController(
            self.client, self._send_ir, self.settings.get(CONF_WAKE_TIMEOUT, DEFAULT_WAKE_TIMEOUT)
        )
        self.unsupported_commands = set()
        self.panasonic = None
        if supports_daylight(self.settings) and self.settings.get("panasonic_enabled", True):
            self.panasonic = PanasonicClient(
                self.settings[CONF_HOST], self.settings.get("panasonic_port", 1024),
                self.settings.get("panasonic_username", "admin1"),
                self.settings.get("panasonic_password", self.settings.get(CONF_PASSWORD, "")),
            )

    async def async_daylight(self, mode):
        """Send once, then refresh actual state even if the response is lost."""
        try:
            async with self.wake.lock:
                if self.panasonic is None or (self.data or {}).get("power") != "1":
                    raise HomeAssistantError("Daylight View requires an online, projecting Panasonic")
                await self.panasonic.daylight(mode)
        except PJLinkError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.async_request_refresh()

    async def _send_ir(self):
        await async_remote_command(self.hass, self.settings)

    async def async_command(self, name, value):
        """Serialize a network control with wake/polling; never use IR for it."""
        try:
            async with self.wake.lock:
                await self.client.command(name, value)
        except PJLinkError as err:
            raise HomeAssistantError(str(err)) from err
        finally:
            await self.async_request_refresh()

    async def _optional_query(self, data, field, command, parser):
        if command in self.unsupported_commands:
            data["query_errors"][command] = "unsupported"
            return
        try:
            data[field] = parser(await self.client.command(command))
        except CommandError as err:
            if err.code == "ERR1":
                self.unsupported_commands.add(command)
            data["query_errors"][command] = err.code
        except PJLinkError as err:
            data["query_errors"][command] = str(err)

    async def _async_update_data(self):
        async with self.wake.lock:
            try:
                power = await self.client.power()
            except PJLinkError as err:
                return {"connected": False, "power": None, "error": str(err)}
            data = {
                "connected": True,
                "power": power,
                "source": None,
                "muted": None,
                "video_muted": None,
                "inputs": [],
                "lamps": None,
                "errors": None,
                "query_errors": {},
                "daylight_view": None,
            }
            # Status queries only; they never send Power On, including in standby.
            await self._optional_query(data, "lamps", "LAMP", parse_lamps)
            await self._optional_query(data, "errors", "ERST", parse_errors)
            if power != "1":
                return data
            if self.panasonic is not None:
                try:
                    data["daylight_view"] = await self.panasonic.daylight()
                except PJLinkError as err:
                    data["query_errors"]["daylight_view"] = str(err)
            for field, command in (("source", "INPT"), ("muted", "AVMT"), ("inputs", "INST")):
                try:
                    value = await self.client.command(command)
                    if field == "inputs":
                        values = value.split()
                        if not values or not all(re.fullmatch(r"[1-5][1-9]", item) for item in values):
                            raise PJLinkError("Invalid PJLink input list")
                        data[field] = values
                    elif field == "source":
                        if not re.fullmatch(r"[1-5][1-9]", value):
                            raise PJLinkError("Invalid PJLink input")
                        data[field] = value
                    else:
                        if value not in ("10", "11", "20", "21", "30", "31"):
                            raise PJLinkError("Invalid PJLink mute state")
                        data[field] = value in ("21", "31")
                        data["video_muted"] = value in ("11", "31")
                except (CommandError, PJLinkError) as err:
                    data["error"] = str(err)
            return data
