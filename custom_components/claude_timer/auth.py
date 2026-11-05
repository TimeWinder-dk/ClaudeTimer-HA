"""OAuth-tokens: PKCE-login, kode-ombytning og robust fornyelse.

Forskelle fra hass-claude-usage, som denne del er inspireret af:

* Kun et afvist refresh-token (400/401/403) kræver nyt login. 429, 5xx og
  netværksfejl er midlertidige; tokens bevares, og der prøves igen senere.
* Et 401 fra API'et udløser én tvungen fornyelse og ét nyt forsøg, før der
  bedes om nyt login.
* Fornyelse sker under en lås (single-flight), så det roterende refresh-token
  aldrig bruges to gange samtidig.
* Det nye token-sæt gemmes, før det tages i brug.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPES,
    OAUTH_TOKEN_URL,
    REQUEST_TIMEOUT,
    TOKEN_REFRESH_MARGIN,
)

_LOGGER = logging.getLogger(__name__)

# Fejl-koder fra token-endpointet, der betyder at tilladelsen er væk for godt.
_PERMANENT_ERRORS = {"invalid_grant", "invalid_client", "unauthorized_client"}


class AuthError(Exception):
    """Tilladelsen er ugyldig; brugeren skal logge ind igen."""


class TransientError(Exception):
    """Midlertidig fejl; prøv igen senere uden at røre ved tokens."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float  # unix-sekunder

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> TokenSet:
        return cls(
            access_token=data.get(CONF_ACCESS_TOKEN, ""),
            refresh_token=data.get(CONF_REFRESH_TOKEN, ""),
            expires_at=float(data.get(CONF_EXPIRES_AT, 0)),
        )

    def as_data(self) -> dict[str, Any]:
        return {
            CONF_ACCESS_TOKEN: self.access_token,
            CONF_REFRESH_TOKEN: self.refresh_token,
            CONF_EXPIRES_AT: self.expires_at,
        }


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(challenge: str, state: str) -> str:
    return f"{OAUTH_AUTHORIZE_URL}?" + urlencode(
        {
            "code": "true",
            "client_id": OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": OAUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )


def split_pasted_code(pasted: str) -> tuple[str, str | None]:
    """Accepterer 'kode#state', blot 'kode' eller hele callback-URL'en."""
    text = pasted.strip()
    if text.startswith("http"):
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        code = (query.get("code") or [""])[0]
        state = (query.get("state") or [None])[0]
        if parsed.fragment and not state:
            state = parsed.fragment
        return code, state
    code, _, state = text.partition("#")
    return code.strip(), (state.strip() or None)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


async def _post_token(session: aiohttp.ClientSession, payload: dict[str, Any]) -> dict[str, Any]:
    """POST til token-endpointet og klassificér fejl."""
    try:
        async with session.post(
            OAUTH_TOKEN_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            status = resp.status
            try:
                body = await resp.json(content_type=None)
            except ValueError:
                body = None
            retry_after = parse_retry_after(resp.headers.get("Retry-After"))
    except (aiohttp.ClientError, TimeoutError) as err:
        raise TransientError(f"Token-endpointet kunne ikke kontaktes: {err}") from err

    error = body.get("error") if isinstance(body, dict) else None
    if status in (400, 401, 403) or error in _PERMANENT_ERRORS:
        raise AuthError(f"Tilladelsen blev afvist ({status}, {error or 'ukendt'})")
    if status >= 300:  # 429, 5xx m.m.
        raise TransientError(f"Token-endpointet svarede {status}", retry_after)
    if not isinstance(body, dict) or not body.get("access_token"):
        raise TransientError("Token-svaret manglede access_token")
    return body


def _token_set(body: dict[str, Any], previous_refresh: str, started: float) -> TokenSet:
    expires_in = body.get("expires_in")
    if not isinstance(expires_in, (int, float)) or expires_in <= 0:
        expires_in = 3600
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token") or previous_refresh,
        # Regn fra før forespørgslen, så netværkstid ikke forlænger levetiden.
        expires_at=started + float(expires_in),
    )


async def async_exchange_code(
    session: aiohttp.ClientSession, code: str, state: str, verifier: str
) -> TokenSet:
    started = time.time()
    body = await _post_token(
        session,
        {
            "grant_type": "authorization_code",
            "code": code,
            "state": state,
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    if not body.get("refresh_token"):
        raise AuthError("Login gav ikke et refresh-token")
    return _token_set(body, "", started)


class TokenManager:
    """Udleverer et gyldigt adgangstoken og fornyer det sikkert."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: TokenSet,
        on_update: Callable[[TokenSet], None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._on_update = on_update
        self._clock = clock
        self._lock = asyncio.Lock()

    @property
    def tokens(self) -> TokenSet:
        return self._tokens

    def _fresh(self) -> bool:
        return bool(self._tokens.access_token) and (
            self._clock() < self._tokens.expires_at - TOKEN_REFRESH_MARGIN
        )

    async def async_get_access_token(self, rejected: str | None = None) -> str:
        """Returnér et gyldigt token.

        `rejected` er et token, API'et lige har afvist med 401; så fornyes der,
        medmindre en anden kaldsti allerede har skiftet tokenet ud.
        """
        if rejected is None and self._fresh():
            return self._tokens.access_token
        async with self._lock:
            current = self._tokens
            if rejected is None and self._fresh():
                return current.access_token
            if rejected is not None and current.access_token != rejected:
                return current.access_token
            return (await self._refresh(current)).access_token

    async def _refresh(self, current: TokenSet) -> TokenSet:
        if not current.refresh_token:
            raise AuthError("Intet refresh-token")
        started = self._clock()
        body = await _post_token(
            self._session,
            {
                "grant_type": "refresh_token",
                "refresh_token": current.refresh_token,
                "client_id": OAUTH_CLIENT_ID,
            },
        )
        new = _token_set(body, current.refresh_token, started)
        # Gem først: er refresh-tokenet roteret, er det gamle nu ubrugeligt.
        self._on_update(new)
        self._tokens = new
        _LOGGER.debug("Adgangstoken fornyet; udløber om %.0f s", new.expires_at - started)
        return new
