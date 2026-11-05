"""Claude Timer: Claude-forbrug, nulstillinger og prognoser i Home Assistant."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import ClaudeApi
from .auth import TokenManager, TokenSet
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import ClaudeTimerConfigEntry, ClaudeTimerCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = "/claude_timer/claude-timer-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "claude-timer-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Gør custom:claude-timer-card tilgængeligt uden manuel resource."""
    version = int((await hass.async_add_executor_job(CARD_PATH.stat)).st_mtime)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


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
