"""Diagnostik med tokens og personlige oplysninger fjernet."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_EMAIL,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_NAME,
    CONF_REFRESH_TOKEN,
)
from .coordinator import ClaudeTimerConfigEntry

TO_REDACT = {CONF_ACCESS_TOKEN, CONF_REFRESH_TOKEN, CONF_ACCOUNT_EMAIL, CONF_ACCOUNT_ID, CONF_ACCOUNT_NAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClaudeTimerConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "last_update_success": coordinator.last_update_success,
        "rate_limited_until": coordinator.backoff_until.isoformat() if coordinator.backoff_until else None,
        "snapshot": asdict(data) if data else None,
    }
