"""Config flow: login med Claude via PKCE og indsat kode."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import async_fetch_profile
from .auth import (
    AuthError,
    TransientError,
    async_exchange_code,
    authorize_url,
    generate_pkce,
    split_pasted_code,
)
from .const import (
    CONF_ACCOUNT_EMAIL,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_NAME,
    CONF_AUTH_CODE,
    CONF_ORGANIZATION_NAME,
    CONF_PLAN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CODE_SCHEMA = vol.Schema({vol.Required(CONF_AUTH_CODE): str})


class ClaudeTimerConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._verifier, self._challenge = generate_pkce()
        self._state = secrets.token_urlsafe(32)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_step_code("user", user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_code("reauth_confirm", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_step_code("reconfigure", user_input)

    async def _async_step_code(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            code, state = split_pasted_code(user_input[CONF_AUTH_CODE])
            if not code:
                errors["base"] = "missing_code"
            elif state is not None and state != self._state:
                # Koden hører til et andet login-forsøg (eller er forfalsket).
                errors["base"] = "state_mismatch"
            else:
                session = async_get_clientsession(self.hass)
                try:
                    tokens = await async_exchange_code(session, code, self._state, self._verifier)
                    profile = await async_fetch_profile(session, tokens.access_token)
                except AuthError:
                    errors["base"] = "invalid_code"
                except TransientError:
                    _LOGGER.warning("Login mod Claude fejlede midlertidigt", exc_info=True)
                    errors["base"] = "cannot_connect"
                else:
                    data = {
                        **tokens.as_data(),
                        CONF_ACCOUNT_ID: profile.account_id,
                        CONF_ACCOUNT_NAME: profile.name,
                        CONF_ACCOUNT_EMAIL: profile.email,
                        CONF_ORGANIZATION_NAME: profile.organization,
                        CONF_PLAN: profile.plan,
                    }
                    await self.async_set_unique_id(profile.account_id)
                    if self.source == SOURCE_REAUTH:
                        # Reauth må ikke stille stille skifte konto.
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(), data_updates=data
                        )
                    if self.source == SOURCE_RECONFIGURE:
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                        return self.async_update_reload_and_abort(
                            self._get_reconfigure_entry(), data_updates=data
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=profile.title,
                        data=data,
                        options={CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL},
                    )

        return self.async_show_form(
            step_id=step_id,
            data_schema=CODE_SCHEMA,
            description_placeholders={"url": authorize_url(self._challenge, self._state)},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClaudeTimerOptionsFlow()


class ClaudeTimerOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UPDATE_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
                    )
                }
            ),
        )
