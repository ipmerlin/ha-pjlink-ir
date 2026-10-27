"""UI setup, IR learning progress and reconfiguration."""

import asyncio

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .client import AuthenticationError, PJLinkClient, PJLinkError
from .const import (
    CONF_IR_COMMAND,
    CONF_IR_DEVICE,
    CONF_REMOTE,
    CONF_WAKE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_WAKE_TIMEOUT,
    DOMAIN,
)
from .remote import async_remote_command, check_remote
from .panasonic import supports_daylight


class PJLinkIRConfigFlow(ConfigFlow, domain=DOMAIN):
    """Keep learned codes inside the remote integration's standard storage."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PanasonicOptionsFlow()

    def __init__(self):
        self._settings = {}
        self._learn_task = None
        self._learn_error = False
        self._reconfigure_entry = None

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            if not host or any(char.isspace() for char in host) or "/" in host:
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(f"{host}:{user_input[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                self._settings = {**user_input, CONF_HOST: host}
                client = PJLinkClient(host, user_input[CONF_PORT], user_input.get(CONF_PASSWORD, ""))
                try:
                    self._settings.update(await client.identify())
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except PJLinkError:
                    errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_ir()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._settings.get(CONF_HOST, "")): str,
                    vol.Required(CONF_PORT, default=self._settings.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Optional(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._settings = dict(self._reconfigure_entry.data)
        return await self.async_step_ir()

    async def async_step_ir(self, user_input=None):
        errors = {}
        if user_input is not None:
            action = user_input.pop("command_setup")
            self._settings.update(user_input)
            self._settings[CONF_IR_DEVICE] = self._settings[CONF_IR_DEVICE].strip()
            self._settings[CONF_IR_COMMAND] = self._settings[CONF_IR_COMMAND].strip()
            if not self._settings[CONF_IR_COMMAND]:
                errors["base"] = "empty_command"
            else:
                try:
                    check_remote(self.hass, self._settings, learn=action == "learn")
                except HomeAssistantError:
                    errors["base"] = "remote_unavailable" if action == "saved" else "cannot_learn"
                else:
                    if action == "learn":
                        return await self.async_step_learn_start()
                    return self._finish()
        return self.async_show_form(
            step_id="ir",
            description_placeholders={
                "manufacturer": self._settings.get("manufacturer", "—"),
                "model": self._settings.get("model", "—"),
            },
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REMOTE,
                        **({"default": self._settings[CONF_REMOTE]} if CONF_REMOTE in self._settings else {}),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="remote")),
                    vol.Required(
                        CONF_IR_DEVICE, default=self._settings.get(CONF_IR_DEVICE, "panasonic_projector")
                    ): str,
                    vol.Required(CONF_IR_COMMAND, default=self._settings.get(CONF_IR_COMMAND, "power_on")): str,
                    vol.Required("command_setup", default="saved"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["saved", "learn"],
                            translation_key="command_setup",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_WAKE_TIMEOUT, default=self._settings.get(CONF_WAKE_TIMEOUT, DEFAULT_WAKE_TIMEOUT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
                }
            ),
            errors=errors,
        )

    async def async_step_learn_start(self, user_input=None):
        if user_input is not None:
            self._learn_task = None
            self._learn_error = False
            return await self.async_step_learn()
        return self.async_show_form(step_id="learn_start", data_schema=vol.Schema({}))

    async def _async_learn(self):
        try:
            async with asyncio.timeout(75):
                await async_remote_command(self.hass, self._settings, learn=True)
        except Exception:  # Third-party remote errors must not break the wizard.
            self._learn_error = True

    async def async_step_learn(self, user_input=None):
        if self._learn_task is None:
            self._learn_task = self.hass.async_create_task(self._async_learn())
            return self.async_show_progress(step_id="learn", progress_action="learning", progress_task=self._learn_task)
        if not self._learn_task.done():
            return self.async_show_progress(step_id="learn", progress_action="learning", progress_task=self._learn_task)
        # Retrieving result also surfaces unexpected errors rather than claiming success.
        self._learn_task.result()
        return self.async_show_progress_done(next_step_id="learn_failed" if self._learn_error else "learn_confirm")

    async def async_step_learn_failed(self, user_input=None):
        if user_input is not None:
            return await self.async_step_learn_start()
        return self.async_show_form(step_id="learn_failed", data_schema=vol.Schema({}))

    async def async_step_learn_confirm(self, user_input=None):
        if user_input is not None:
            if user_input["confirmed"]:
                return self._finish()
            return await self.async_step_learn_start()
        return self.async_show_form(
            step_id="learn_confirm", data_schema=vol.Schema({vol.Required("confirmed", default=False): bool})
        )

    def _finish(self):
        if self._reconfigure_entry is not None:
            self.hass.config_entries.async_update_entry(
                self._reconfigure_entry, data={**self._reconfigure_entry.data, **self._settings}
            )
            return self.async_abort(reason="reconfigure_successful")
        title = (
            self._settings.get("name")
            or " ".join(filter(None, (self._settings.get("manufacturer"), self._settings.get("model"))))
            or self._settings[CONF_HOST]
        )
        return self.async_create_entry(title=title, data=self._settings)


class PanasonicOptionsFlow(OptionsFlow):
    """Independent LAN settings; do not repeat IR learning to change them."""

    async def async_step_init(self, user_input=None):
        if not supports_daylight(self.config_entry.data):
            return self.async_abort(reason="daylight_not_supported")
        if user_input is not None:
            return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})
        settings = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("panasonic_enabled", default=settings.get("panasonic_enabled", True)): bool,
                vol.Required("panasonic_port", default=settings.get("panasonic_port", 1024)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Required("panasonic_username", default=settings.get("panasonic_username", "admin1")): str,
                vol.Optional("panasonic_password", default=settings.get(
                    "panasonic_password", settings.get(CONF_PASSWORD, "")
                )): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            }),
        )
