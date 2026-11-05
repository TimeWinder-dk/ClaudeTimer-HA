"""Indlæs integrationens rene moduler uden Home Assistant.

Pakkens __init__.py importerer homeassistant, så vi registrerer pakken med
__path__ uden at køre den. Mangler aiohttp (fx bag en firewall), bruges en
minimal stub med de navne, modulerne refererer til.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG_DIR = ROOT / "custom_components" / "claude_timer"

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    stub.ClientError = ClientError
    stub.ClientTimeout = ClientTimeout
    stub.ClientSession = object
    sys.modules["aiohttp"] = stub

for name, path in (
    ("custom_components", ROOT / "custom_components"),
    ("custom_components.claude_timer", PKG_DIR),
):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

import aiohttp  # noqa: E402

from custom_components.claude_timer import api, auth, usage  # noqa: E402,F401


class FakeResponse:
    def __init__(self, status: int, body=None, headers=None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def json(self, content_type=None):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Svarer med køer af svar per metode og husker kaldene."""

    def __init__(self, posts=(), gets=()) -> None:
        self.posts = list(posts)
        self.gets = list(gets)
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def _next(self, queue):
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": json})
        return self._next(self.posts)

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append({"url": url, "headers": headers})
        return self._next(self.gets)
