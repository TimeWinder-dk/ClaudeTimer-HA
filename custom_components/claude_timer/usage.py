"""Parsing af usage-svaret og prognoser.

Rent Python uden Home Assistant-afhængigheder, så det kan testes direkte.
Logikken spejler Windows-appen (ClaudeUsageClient.BuildWindows og
UsageCardViewModel.Pace), så de to løsninger viser de samme tal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import CRITICAL_FROM, WARNING_FROM

WINDOW_LENGTHS: dict[str, timedelta] = {
    "session": timedelta(hours=5),
    "weekly_all": timedelta(days=7),
    "weekly_scoped": timedelta(days=7),
}


@dataclass(frozen=True)
class UsageLimit:
    """Én grænse fra API'ets limits[] (eller det ældre five_hour/seven_day)."""

    kind: str
    group: str
    percent: float
    resets_at: datetime | None
    model: str | None = None
    surface: str | None = None
    severity: str | None = None
    is_active: bool | None = None

    @property
    def key(self) -> str:
        """Stabil identitet; flere weekly_scoped adskilles af model/overflade."""
        parts = [self.kind]
        if self.model:
            parts.append(slugify(self.model))
        if self.surface:
            parts.append(slugify(self.surface))
        return "_".join(parts)

    @property
    def object_slug(self) -> str:
        """Kort, sprog-uafhængig del af entity_id, fx 'session' eller 'weekly_fable'."""
        if self.kind == "session" and not (self.model or self.surface):
            return "session"
        if self.kind == "weekly_all" and not (self.model or self.surface):
            return "weekly"
        if self.kind == "weekly_scoped" and self.model:
            return "_".join(
                ["weekly", slugify(self.model)] + ([slugify(self.surface)] if self.surface else [])
            )
        return self.key

    @property
    def window_length(self) -> timedelta | None:
        return WINDOW_LENGTHS.get(self.kind)

    @property
    def level(self) -> str:
        return usage_level(self.percent)

    def translation(self) -> tuple[str, dict[str, str]]:
        """Oversættelsesnøgle-præfiks og pladsholdere til entitetsnavne."""
        if self.kind == "session" and not (self.model or self.surface):
            return "session", {}
        if self.kind == "weekly_all" and not (self.model or self.surface):
            return "weekly", {}
        if self.kind == "weekly_scoped" and self.model:
            model = f"{self.model} ({self.surface})" if self.surface else self.model
            return "weekly_model", {"model": model}
        label = self.kind.replace("_", " ").capitalize()
        extras = [x for x in (self.model, self.surface) if x]
        if extras:
            label = f"{label} ({', '.join(extras)})"
        return "other", {"limit": label}


@dataclass(frozen=True)
class ExtraUsage:
    """Ekstra forbrug (betalt overforbrug), hvis kontoen har det."""

    enabled: bool
    percent: float | None = None
    used: float | None = None
    limit: float | None = None
    currency: str | None = None


@dataclass(frozen=True)
class UsageSnapshot:
    limits: dict[str, UsageLimit]
    extra: ExtraUsage | None
    fetched_at: datetime

    @property
    def next_reset(self) -> datetime | None:
        resets = [lim.resets_at for lim in self.limits.values() if lim.resets_at]
        return min(resets) if resets else None


@dataclass(frozen=True)
class Forecast:
    """Lineær fremskrivning af forbruget til vinduets nulstilling."""

    projected_percent: float | None
    hits_limit_at: datetime | None
    elapsed_percent: float | None
    over_pace: bool

    @property
    def available(self) -> bool:
        return self.projected_percent is not None


NO_FORECAST = Forecast(None, None, None, False)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "x"


def usage_level(percent: float) -> str:
    if percent >= CRITICAL_FROM:
        return "critical"
    if percent >= WARNING_FROM:
        return "warning"
    return "good"


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_usage(raw: dict[str, Any], now: datetime) -> UsageSnapshot:
    """Byg et snapshot. Foretrækker limits[], falder tilbage til ældre felter."""
    limits: dict[str, UsageLimit] = {}
    for item in raw.get("limits") or []:
        if not isinstance(item, dict) or not item.get("kind"):
            continue
        scope = item.get("scope") or {}
        model = (scope.get("model") or {}).get("display_name") or None
        surface = scope.get("surface") or None
        limit = UsageLimit(
            kind=str(item["kind"]),
            group=str(item.get("group") or item["kind"]),
            percent=_number(item.get("percent")) or 0.0,
            resets_at=parse_datetime(item.get("resets_at")),
            model=model,
            surface=str(surface) if surface else None,
            severity=item.get("severity"),
            is_active=item.get("is_active"),
        )
        limits.setdefault(limit.key, limit)

    if not limits:
        for field, kind, group in (
            ("five_hour", "session", "session"),
            ("seven_day", "weekly_all", "weekly"),
        ):
            window = raw.get(field)
            if isinstance(window, dict):
                limit = UsageLimit(
                    kind=kind,
                    group=group,
                    percent=_number(window.get("utilization")) or 0.0,
                    resets_at=parse_datetime(window.get("resets_at")),
                )
                limits[limit.key] = limit

    return UsageSnapshot(limits=limits, extra=_parse_extra(raw), fetched_at=now)


def _parse_extra(raw: dict[str, Any]) -> ExtraUsage | None:
    # Ældre skema: extra_usage med beløb i mindste møntenhed.
    extra = raw.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled"):
        divisor = 10 ** int(extra.get("decimal_places", 2))
        used = _number(extra.get("used_credits"))
        limit = _number(extra.get("monthly_limit"))
        return ExtraUsage(
            enabled=True,
            percent=_number(extra.get("utilization")),
            used=used / divisor if used is not None else None,
            limit=limit / divisor if limit is not None else None,
            currency=extra.get("currency"),
        )
    # Nyere skema: spend med {amount_minor, currency, exponent}.
    spend = raw.get("spend")
    if isinstance(spend, dict) and spend.get("enabled"):
        used = spend.get("used") or {}
        cap = spend.get("limit") or {}
        used_amount = _number(used.get("amount_minor"))
        cap_amount = _number(cap.get("amount_minor"))
        return ExtraUsage(
            enabled=True,
            percent=_number(spend.get("percent")),
            used=used_amount / 10 ** int(used.get("exponent", 2)) if used_amount is not None else None,
            limit=cap_amount / 10 ** int(cap.get("exponent", 2)) if cap_amount is not None else None,
            currency=used.get("currency") or cap.get("currency"),
        )
    if extra is not None or spend is not None:
        return ExtraUsage(enabled=False)
    return None


def forecast(limit: UsageLimit, now: datetime) -> Forecast:
    """Holder tempoet til nulstilling, eller hvornår rammes 100 %?

    Samme regel som Windows-appen: ingen prognose de første 5 % af vinduet
    (mindst 10 minutter) eller under 1 % forbrug, da den så kun er støj.
    """
    percent = limit.percent
    if percent >= 100:
        return Forecast(percent, None, None, True)

    length = limit.window_length
    reset = limit.resets_at
    if length is None or reset is None or reset <= now:
        return NO_FORECAST

    elapsed = length - (reset - now)
    minimum = max(length / 20, timedelta(minutes=10))
    if elapsed < minimum or percent < 1:
        return NO_FORECAST

    elapsed_percent = round(elapsed / length * 100, 1)
    projected = percent * (length / elapsed)
    if projected < 100:
        return Forecast(round(projected, 1), None, elapsed_percent, False)

    hits_at = now + elapsed * ((100 - percent) / percent)
    return Forecast(round(projected, 1), hits_at, elapsed_percent, True)
