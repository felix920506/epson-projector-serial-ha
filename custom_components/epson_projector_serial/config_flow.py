"""Config flow for the Epson Projector (serial bridge) integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import DEFAULT_NAME, DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import EpsonConfigEntry
from .protocol import EpsonConnectionError, EpsonError, EpsonSerialBridge

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
    }
)

SCAN_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=2, max=300, step=1, mode=NumberSelectorMode.BOX)
)


async def _async_check_projector(host: str, port: int) -> str | None:
    """Query the projector, returning an error key if it did not answer."""
    bridge = EpsonSerialBridge(host, port)
    try:
        await bridge.async_query_power()
    except EpsonConnectionError:
        return "cannot_connect"
    except EpsonError:
        return "invalid_response"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error connecting to %s", bridge.target)
        return "unknown"
    return None


class EpsonProjectorSerialConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for a projector behind a serial bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the bridge address and check that the projector answers."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await _async_check_projector(host, port)
            if error is None:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the bridge address change without losing the entity."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            unique_id = f"{host}:{port}"

            if any(
                other.entry_id != entry.entry_id and other.unique_id == unique_id
                for other in self._async_current_entries()
            ):
                errors["base"] = "already_configured"
            elif (error := await _async_check_projector(host, port)) is not None:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    title=user_input[CONF_NAME],
                    data_updates=user_input,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: EpsonConfigEntry) -> EpsonProjectorOptionsFlow:
        """Return the options flow."""
        return EpsonProjectorOptionsFlow()


class EpsonProjectorOptionsFlow(OptionsFlow):
    """Let the polling interval be tuned after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current
                    ): SCAN_INTERVAL_SELECTOR
                }
            ),
        )
