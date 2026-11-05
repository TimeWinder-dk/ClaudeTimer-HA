"""Fælles basis for Claude Timer-entiteter."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT_EMAIL, CONF_ACCOUNT_NAME, CONF_ORGANIZATION_NAME, CONF_PLAN, DOMAIN
from .coordinator import ClaudeTimerConfigEntry, ClaudeTimerCoordinator
from .usage import UsageLimit


def device_info(entry: ClaudeTimerConfigEntry) -> DeviceInfo:
    name = entry.data.get(CONF_ACCOUNT_NAME) or entry.data.get(CONF_ACCOUNT_EMAIL) or "Claude"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Claude · {name}",
        model=entry.data.get(CONF_PLAN) or "Claude",
        manufacturer=entry.data.get(CONF_ORGANIZATION_NAME),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://claude.ai/settings/usage",
    )


class ClaudeTimerEntity(CoordinatorEntity[ClaudeTimerCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ClaudeTimerCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = device_info(entry)


class LimitEntity(ClaudeTimerEntity):
    """En entitet knyttet til én grænse (session, uge, model-uge …)."""

    metric: str

    def __init__(self, coordinator: ClaudeTimerCoordinator, limit: UsageLimit, domain: str) -> None:
        super().__init__(coordinator, f"{limit.key}_{self.metric}")
        self.limit_key = limit.key
        prefix, placeholders = limit.translation()
        self._attr_translation_key = f"{prefix}_{self.metric}"
        self._attr_translation_placeholders = placeholders
        # Sprog-uafhængige entity_id'er, så dashboard og blueprints virker uanset
        # HA's sprog, fx sensor.claude_timer_session_usage.
        self.entity_id = f"{domain}.claude_timer_{limit.object_slug}_{self.metric}"

    @property
    def limit(self) -> UsageLimit | None:
        data = self.coordinator.data
        return data.limits.get(self.limit_key) if data else None

    @property
    def available(self) -> bool:
        # En grænse der forsvinder fra svaret bliver utilgængelig; historikken bevares.
        return super().available and self.limit is not None


def track_limits(
    coordinator: ClaudeTimerCoordinator,
    entry: ClaudeTimerConfigEntry,
    add: Callable[[Iterable[Entity]], None],
    factory: Callable[[UsageLimit], Iterable[Entity]],
) -> None:
    """Tilføj entiteter for nye grænser, efterhånden som de dukker op."""
    known: set[str] = set()

    def _sync() -> None:
        if not coordinator.data:
            return
        new = [lim for key, lim in coordinator.data.limits.items() if key not in known]
        if new:
            known.update(lim.key for lim in new)
            add([entity for lim in new for entity in factory(lim)])

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
