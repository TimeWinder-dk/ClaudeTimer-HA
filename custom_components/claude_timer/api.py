"""Kald til Claudes OAuth usage- og profil-endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

from .auth import AuthError, TokenManager, TransientError, parse_retry_after
from .const import API_BASE_URL, API_BETA_HEADER, PROFILE_PATH, REQUEST_TIMEOUT, USAGE_PATH


class RateLimitedError(TransientError):
    """API'et svarede 429."""


@dataclass(frozen=True)
class Profile:
    account_id: str
    email: str | None
    name: str | None
    organization: str | None
    plan: str | None

    @property
    def title(self) -> str:
        base = self.name or self.email or "Claude"
        return f"{base} ({self.plan})" if self.plan else base


async def async_request_json(
    session: aiohttp.ClientSession, path: str, access_token: str
) -> tuple[int, Any, float | None]:
    """GET med bearer-token. Returnerer (status, json, retry_after)."""
    try:
        async with session.get(
            f"{API_BASE_URL}{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "anthropic-beta": API_BETA_HEADER,
            },
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            status = resp.status
            retry_after = parse_retry_after(resp.headers.get("Retry-After"))
            body = await resp.json(content_type=None) if status < 300 else None
            return status, body, retry_after
    except ValueError as err:
        raise TransientError("Claude returnerede et ukendt svarformat") from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise TransientError(f"Claude kunne ikke kontaktes: {err}") from err


def _check(status: int, body: Any, retry_after: float | None) -> dict[str, Any]:
    if status in (401, 403):
        raise AuthError(f"Claude afviste tokenet ({status})")
    if status == 429:
        raise RateLimitedError("Claude rate-limiter forespørgsler (429)", retry_after)
    if status >= 300:
        raise TransientError(f"Claude returnerede HTTP {status}", retry_after)
    if not isinstance(body, dict):
        raise TransientError("Claude returnerede et tomt svar")
    return body


def parse_profile(body: dict[str, Any]) -> Profile:
    account = body.get("account") or {}
    organization = body.get("organization") or {}
    account_id = account.get("uuid") or account.get("id") or account.get("email")
    if not account_id:
        raise TransientError("Profilen indeholdt ingen konto")
    plan = None
    if account.get("has_claude_max"):
        plan = "Max"
    elif account.get("has_claude_pro"):
        plan = "Pro"
    return Profile(
        account_id=str(account_id),
        email=account.get("email"),
        name=account.get("display_name") or account.get("full_name"),
        organization=organization.get("name"),
        plan=plan,
    )


async def async_fetch_profile(session: aiohttp.ClientSession, access_token: str) -> Profile:
    return parse_profile(_check(*await async_request_json(session, PROFILE_PATH, access_token)))


class ClaudeApi:
    def __init__(self, session: aiohttp.ClientSession, tokens: TokenManager) -> None:
        self._session = session
        self._tokens = tokens

    async def _get(self, path: str) -> dict[str, Any]:
        token = await self._tokens.async_get_access_token()
        status, body, retry_after = await async_request_json(self._session, path, token)
        if status == 401:
            # Tokenet kan være tilbagekaldt før tid: forny én gang og prøv igen.
            token = await self._tokens.async_get_access_token(rejected=token)
            status, body, retry_after = await async_request_json(self._session, path, token)
        return _check(status, body, retry_after)

    async def async_get_usage(self) -> dict[str, Any]:
        return await self._get(USAGE_PATH)

    async def async_get_profile(self) -> Profile:
        return parse_profile(await self._get(PROFILE_PATH))
