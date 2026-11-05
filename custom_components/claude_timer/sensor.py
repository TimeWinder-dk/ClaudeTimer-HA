"""Sensorer: forbrug, nulstilling og prognose per grænse."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ClaudeTimerConfigEntry, ClaudeTimerCoordinator
from .entity import ClaudeTimerEntity, LimitEntity, track_limits
from .usage import UsageLimit, forecast


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeTimerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([LastFetchedSensor(coordinator)])
    if coordinator.data and coordinator.data.extra is not None:
        async_add_entities([ExtraUsageSensor(coordinator)])
    track_limits(
        coordinator,
        entry,
        async_add_entities,
        lambda lim: [
            UsageSensor(coordinator, lim),
            ResetSensor(coordinator, lim),
            ForecastSensor(coordinator, lim),
        ],
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class UsageSensor(LimitEntity, SensorEntity):
    """Forbrug i procent. Attributterne rummer alt, et kort eller en gauge skal bruge."""

    metric = "usage"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ClaudeTimerCoordinator, limit: UsageLimit) -> None:
        super().__init__(coordinator, limit, "sensor")

    @property
    def native_value(self) -> float | None:
        return self.limit.percent if self.limit else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        limit = self.limit
        if limit is None:
            return None
        fc = forecast(limit, dt_util.utcnow())
        length = limit.window_length
        return {
            "level": limit.level,
            "resets_at": _iso(limit.resets_at),
            "window_hours": length.total_seconds() / 3600 if length else None,
            "forecast_percent": fc.projected_percent,
            "hits_limit_at": _iso(fc.hits_limit_at),
            "elapsed_percent": fc.elapsed_percent,
            "over_pace": fc.over_pace,
            "kind": limit.kind,
            "group": limit.group,
            "model": limit.model,
            "surface": limit.surface,
            "severity": limit.severity,
        }


class ResetSensor(LimitEntity, SensorEntity):
    """Nulstillingstidspunkt. HA viser det som en levende nedtælling ('om 2 timer')."""

    metric = "reset"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ClaudeTimerCoordinator, limit: UsageLimit) -> None:
        super().__init__(coordinator, limit, "sensor")

    @property
    def native_value(self) -> datetime | None:
        return self.limit.resets_at if self.limit else None


class ForecastSensor(LimitEntity, SensorEntity):
    """Forventet forbrug ved nulstilling, hvis tempoet holder."""

    metric = "forecast"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: ClaudeTimerCoordinator, limit: UsageLimit) -> None:
        super().__init__(coordinator, limit, "sensor")

    @property
    def native_value(self) -> float | None:
        if self.limit is None:
            return None
        return forecast(self.limit, dt_util.utcnow()).projected_percent

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.limit is None:
            return None
        fc = forecast(self.limit, dt_util.utcnow())
        return {
            "hits_limit_at": _iso(fc.hits_limit_at),
            "elapsed_percent": fc.elapsed_percent,
            "over_pace": fc.over_pace,
        }


class ExtraUsageSensor(ClaudeTimerEntity, SensorEntity):
    """Ekstra (betalt) forbrug denne måned."""

    _attr_translation_key = "extra_usage"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: ClaudeTimerCoordinator) -> None:
        super().__init__(coordinator, "extra_usage")
        self.entity_id = "sensor.claude_timer_extra_usage"

    @property
    def _extra(self):
        return self.coordinator.data.extra if self.coordinator.data else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        extra = self._extra
        return extra.currency if extra and extra.currency else None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return SensorDeviceClass.MONETARY if self.native_unit_of_measurement else None

    @property
    def native_value(self) -> float | None:
        extra = self._extra
        if extra is None:
            return None
        return extra.used if extra.enabled else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        extra = self._extra
        if extra is None:
            return None
        return {"enabled": extra.enabled, "percent": extra.percent, "limit": extra.limit}


class LastFetchedSensor(ClaudeTimerEntity, SensorEntity):
    """Hvornår data sidst blev hentet; nyttig når API'et rate-limiter."""

    _attr_translation_key = "last_fetched"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ClaudeTimerCoordinator) -> None:
        super().__init__(coordinator, "last_fetched")
        self.entity_id = "sensor.claude_timer_last_fetched"

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.fetched_at if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        backoff = self.coordinator.backoff_until
        return {
            "last_update_success": self.coordinator.last_update_success,
            "rate_limited_until": _iso(backoff),
        }
