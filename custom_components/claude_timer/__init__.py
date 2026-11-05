"""Claude Timer: Claude-forbrug, nulstillinger og prognoser i Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ClaudeApi
from .auth import TokenManager, TokenSet
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
from .coordinator import ClaudeTimerConfigEntry, ClaudeTimerCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ClaudeTimerConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    def _persist(tokens: TokenSet) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **tokens.as_data()})

    tokens = TokenManager(session, TokenSet.from_data(dict(entry.data)), _persist)
    coordinator = ClaudeTimerCoordinator(hass, entry, ClaudeApi(session, tokens))
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Kaldes også når tokens gemmes; derfor kun en billig justering, ingen reload.
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ClaudeTimerConfigEntry) -> None:
    entry.runtime_data.update_interval = timedelta(
        seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    )


async def async_unload_entry(hass: HomeAssistant, entry: ClaudeTimerConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
