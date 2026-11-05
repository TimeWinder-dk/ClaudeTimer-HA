"""Binær sensor per grænse: er tempoet så højt, at grænsen rammes før nulstilling?"""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import ClaudeTimerConfigEntry, ClaudeTimerCoordinator
from .entity import LimitEntity, track_limits
from .usage import UsageLimit, forecast


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeTimerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    track_limits(coordinator, entry, async_add_entities, lambda lim: [OverPaceSensor(coordinator, lim)])


class OverPaceSensor(LimitEntity, BinarySensorEntity):
    metric = "over_pace"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: ClaudeTimerCoordinator, limit: UsageLimit) -> None:
        super().__init__(coordinator, limit, "binary_sensor")

    @property
    def is_on(self) -> bool | None:
        if self.limit is None:
            return None
        return forecast(self.limit, dt_util.utcnow()).over_pace

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.limit is None:
            return None
        fc = forecast(self.limit, dt_util.utcnow())
        return {"hits_limit_at": fc.hits_limit_at.isoformat() if fc.hits_limit_at else None}
