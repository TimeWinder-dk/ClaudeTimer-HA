"""Kald til Claudes OAuth usage- og profil-endpoints og ChatGPTs usage-endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .auth import AuthError, TokenManager, TransientError, jwt_claims, parse_retry_after
from .const import (
    API_BASE_URL,
    API_BETA_HEADER,
    CHATGPT_ID_CLAIM,
    CHATGPT_USAGE_URL,
    PROFILE_PATH,
    PROVIDER_CHATGPT,
    PROVIDER_CLAUDE,
    REQUEST_TIMEOUT,
    USAGE_PATH,
)
from .usage import UsageSnapshot, parse_chatgpt_usage, parse_usage


class RateLimitedError(TransientError):
    """API'et svarede 429."""


@dataclass(frozen=True)
class Profile:
    account_id: str
    email: str | None
    name: str | None
    organization: str | None
    plan: str | None
    provider: str = PROVIDER_CLAUDE
    workspace_id: str | None = None

    @property
    def title(self) -> str:
        if self.provider == PROVIDER_CHATGPT:
            base = f"ChatGPT · {self.email or self.name or 'konto'}"
        else:
            base = self.name or self.email or "Claude"
        return f"{base} ({self.plan})" if self.plan else base


async def _request_json(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str], service: str
) -> tuple[int, Any, float | None]:
    """GET med headers. Returnerer (status, json, retry_after)."""
    try:
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            status = resp.status
            retry_after = parse_retry_after(resp.headers.get("Retry-After"))
            body = await resp.json(content_type=None) if status < 300 else None
            return status, body, retry_after
    except ValueError as err:
        raise TransientError(f"{service} returnerede et ukendt svarformat") from err
    except (aiohttp.ClientError, TimeoutError) as err:
        raise TransientError(f"{service} kunne ikke kontaktes: {err}") from err


async def async_request_json(
    session: aiohttp.ClientSession, path: str, access_token: str
) -> tuple[int, Any, float | None]:
    """GET mod Claudes API med bearer-token."""
    return await _request_json(
        session,
        f"{API_BASE_URL}{path}",
        {"Authorization": f"Bearer {access_token}", "anthropic-beta": API_BETA_HEADER},
        "Claude",
    )


def _check(status: int, body: Any, retry_after: float | None, service: str = "Claude") -> dict[str, Any]:
    if status in (401, 403):
        raise AuthError(f"{service} afviste tokenet ({status})")
    if status == 429:
        raise RateLimitedError(f"{service} rate-limiter forespørgsler (429)", retry_after)
    if status >= 300:
        raise TransientError(f"{service} returnerede HTTP {status}", retry_after)
    if not isinstance(body, dict):
        raise TransientError(f"{service} returnerede et tomt svar")
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


def parse_chatgpt_profile(id_token: str | None, access_token: str) -> Profile:
    """Identiteten bag et ChatGPT-login, læst fra id-tokenet (og adgangstokenet som reserve)."""
    id_claims = jwt_claims(id_token)
    access_claims = jwt_claims(access_token)
    auth = id_claims.get(CHATGPT_ID_CLAIM) or access_claims.get(CHATGPT_ID_CLAIM) or {}
    user_id = auth.get("chatgpt_user_id") or auth.get("user_id") or id_claims.get("sub")
    workspace = auth.get("chatgpt_account_id")
    if not user_id:
        raise AuthError("ChatGPT-loginet indeholdt ingen bruger")
    plan = (access_claims.get(CHATGPT_ID_CLAIM) or {}).get("chatgpt_plan_type") or auth.get("chatgpt_plan_type")
    email = id_claims.get("email") or (access_claims.get("https://api.openai.com/profile") or {}).get("email")
    return Profile(
        # Forbrug gælder pr. bruger og arbejdsområde, så begge indgår i identiteten.
        account_id=f"chatgpt:{user_id}:{workspace or '-'}",
        email=email,
        name=None,
        organization=None,
        plan=f"ChatGPT {plan.capitalize()}" if plan else "ChatGPT",
        provider=PROVIDER_CHATGPT,
        workspace_id=workspace,
    )


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

    @staticmethod
    def parse_usage(raw: dict[str, Any], now: datetime) -> UsageSnapshot:
        return parse_usage(raw, now)


class ChatGptApi:
    """ChatGPTs usage-endpoint, som Codex selv bruger til sin forbrugsmenu."""

    def __init__(
        self, session: aiohttp.ClientSession, tokens: TokenManager, workspace_id: str | None
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._workspace_id = workspace_id

    async def _request(self, token: str) -> tuple[int, Any, float | None]:
        headers = {"Authorization": f"Bearer {token}"}
        if self._workspace_id:
            headers["ChatGPT-Account-Id"] = self._workspace_id
        return await _request_json(self._session, CHATGPT_USAGE_URL, headers, "ChatGPT")

    async def async_get_usage(self) -> dict[str, Any]:
        token = await self._tokens.async_get_access_token()
        status, body, retry_after = await self._request(token)
        if status == 401:
            token = await self._tokens.async_get_access_token(rejected=token)
            status, body, retry_after = await self._request(token)
        return _check(status, body, retry_after, "ChatGPT")

    @staticmethod
    def parse_usage(raw: dict[str, Any], now: datetime) -> UsageSnapshot:
        return parse_chatgpt_usage(raw, now)
