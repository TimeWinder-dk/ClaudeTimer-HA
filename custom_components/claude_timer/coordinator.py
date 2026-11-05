"""DataUpdateCoordinator for Claude Timer."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ClaudeApi, RateLimitedError
from .auth import AuthError, TransientError
from .const import (
    CONF_UPDATE_INTERVAL,
    DEFAULT_RATE_LIMIT_BACKOFF,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    RESET_REFRESH_DELAY,
)
from .usage import UsageSnapshot, parse_usage

_LOGGER = logging.getLogger(__name__)

type ClaudeTimerConfigEntry = ConfigEntry[ClaudeTimerCoordinator]


class ClaudeTimerCoordinator(DataUpdateCoordinator[UsageSnapshot]):
    config_entry: ClaudeTimerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ClaudeTimerConfigEntry, api: ClaudeApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        )
        self.api = api
        self.backoff_until: datetime | None = None
        self._unsub_reset: CALLBACK_TYPE | None = None

    async def _async_update_data(self) -> UsageSnapshot:
        now = dt_util.utcnow()
        # Under en 429-spærring rører vi ikke API'et; hvert kald kan forlænge den.
        if self.backoff_until and now < self.backoff_until:
            raise UpdateFailed(f"Rate-limited til {self.backoff_until.isoformat()}")

        try:
            raw = await self.api.async_get_usage()
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except RateLimitedError as err:
            wait = err.retry_after or DEFAULT_RATE_LIMIT_BACKOFF
            self.backoff_until = now + timedelta(seconds=wait)
            _LOGGER.warning("Claude rate-limiter; venter %.0f minutter", wait / 60)
            raise UpdateFailed(str(err)) from err
        except TransientError as err:
            raise UpdateFailed(str(err)) from err

        self.backoff_until = None
        snapshot = parse_usage(raw, now)
        self._schedule_reset_refresh(snapshot)
        return snapshot

    @callback
    def _schedule_reset_refresh(self, snapshot: UsageSnapshot) -> None:
        """Hent igen lige efter næste nulstilling, hvis den kommer før næste poll."""
        if self._unsub_reset:
            self._unsub_reset()
            self._unsub_reset = None
        reset = snapshot.next_reset
        if reset is None or self.update_interval is None:
            return
        when = reset + timedelta(seconds=RESET_REFRESH_DELAY)
        if when >= snapshot.fetched_at + self.update_interval:
            return

        @callback
        def _refresh(_: datetime) -> None:
            self._unsub_reset = None
            self.hass.async_create_task(self.async_request_refresh())

        self._unsub_reset = async_track_point_in_utc_time(self.hass, _refresh, when)

    async def async_shutdown(self) -> None:
        if self._unsub_reset:
            self._unsub_reset()
            self._unsub_reset = None
        await super().async_shutdown()
