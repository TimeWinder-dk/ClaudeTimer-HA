import asyncio
import unittest

from support import FakeResponse, FakeSession, aiohttp, api, auth

T0 = 1_000_000.0


def manager(session, expires_at=T0 + 3600, saved=None, clock=lambda: T0):
    saved = saved if saved is not None else []
    tokens = auth.TokenSet("old-access", "old-refresh", expires_at)
    return auth.TokenManager(session, tokens, saved.append, clock=clock), saved


def ok_refresh(access="new-access", refresh="new-refresh", expires_in=3600):
    return FakeResponse(200, {"access_token": access, "refresh_token": refresh, "expires_in": expires_in})


class TokenManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_token_is_used_without_refresh(self):
        session = FakeSession()
        tm, saved = manager(session)
        self.assertEqual(await tm.async_get_access_token(), "old-access")
        self.assertEqual(session.post_calls, [])

    async def test_refreshes_before_expiry_and_persists_rotated_token(self):
        session = FakeSession(posts=[ok_refresh()])
        tm, saved = manager(session, expires_at=T0 + 60)  # inden for marginen
        self.assertEqual(await tm.async_get_access_token(), "new-access")
        self.assertEqual(session.post_calls[0]["json"]["refresh_token"], "old-refresh")
        self.assertEqual(saved[0].refresh_token, "new-refresh")
        self.assertEqual(saved[0].expires_at, T0 + 3600)

    async def test_keeps_refresh_token_when_not_rotated(self):
        session = FakeSession(posts=[FakeResponse(200, {"access_token": "a2", "expires_in": 3600})])
        tm, saved = manager(session, expires_at=0)
        await tm.async_get_access_token()
        self.assertEqual(saved[0].refresh_token, "old-refresh")

    async def test_concurrent_callers_refresh_once(self):
        session = FakeSession(posts=[ok_refresh()])
        tm, saved = manager(session, expires_at=0)
        results = await asyncio.gather(*(tm.async_get_access_token() for _ in range(5)))
        self.assertEqual(set(results), {"new-access"})
        self.assertEqual(len(session.post_calls), 1)

    async def test_rejected_token_forces_single_refresh(self):
        session = FakeSession(posts=[ok_refresh()])
        tm, _ = manager(session)
        first = await tm.async_get_access_token(rejected="old-access")
        # Et andet kald med det samme afviste token må ikke forny igen.
        second = await tm.async_get_access_token(rejected="old-access")
        self.assertEqual((first, second), ("new-access", "new-access"))
        self.assertEqual(len(session.post_calls), 1)

    async def test_invalid_grant_requires_reauth(self):
        session = FakeSession(posts=[FakeResponse(400, {"error": "invalid_grant"})])
        tm, saved = manager(session, expires_at=0)
        with self.assertRaises(auth.AuthError):
            await tm.async_get_access_token()
        self.assertEqual(saved, [])

    async def test_server_errors_are_transient_and_keep_tokens(self):
        for response in (
            FakeResponse(503, None),
            FakeResponse(429, None, {"Retry-After": "120"}),
            aiohttp.ClientError("boom"),
            TimeoutError(),
            FakeResponse(200, ValueError("not json")),
        ):
            with self.subTest(response=response):
                session = FakeSession(posts=[response])
                tm, saved = manager(session, expires_at=0)
                with self.assertRaises(auth.TransientError) as ctx:
                    await tm.async_get_access_token()
                self.assertEqual(saved, [])
                self.assertEqual(tm.tokens.refresh_token, "old-refresh")
                if getattr(response, "status", None) == 429:
                    self.assertEqual(ctx.exception.retry_after, 120)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_401_refreshes_and_retries_once(self):
        session = FakeSession(
            posts=[ok_refresh()],
            gets=[FakeResponse(401), FakeResponse(200, {"limits": []})],
        )
        tm, _ = manager(session)
        result = await api.ClaudeApi(session, tm).async_get_usage()
        self.assertEqual(result, {"limits": []})
        self.assertEqual(session.get_calls[1]["headers"]["Authorization"], "Bearer new-access")

    async def test_second_401_requires_reauth(self):
        session = FakeSession(posts=[ok_refresh()], gets=[FakeResponse(401), FakeResponse(401)])
        tm, _ = manager(session)
        with self.assertRaises(auth.AuthError):
            await api.ClaudeApi(session, tm).async_get_usage()

    async def test_429_is_rate_limited_with_retry_after(self):
        session = FakeSession(gets=[FakeResponse(429, None, {"Retry-After": "900"})])
        tm, _ = manager(session)
        with self.assertRaises(api.RateLimitedError) as ctx:
            await api.ClaudeApi(session, tm).async_get_usage()
        self.assertEqual(ctx.exception.retry_after, 900)

    async def test_profile_parsing(self):
        profile = api.parse_profile({
            "account": {"uuid": "u1", "email": "a@b.c", "display_name": "Thomas", "has_claude_max": True},
            "organization": {"name": "Org"},
        })
        self.assertEqual(profile.title, "Thomas (Max)")


def jwt(claims):
    import base64
    import json

    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


CLAIM = "https://api.openai.com/auth"
ID_TOKEN = jwt({"email": "a@b.c", CLAIM: {"chatgpt_user_id": "user-7", "chatgpt_account_id": "ws-1"}})
ACCESS_TOKEN = jwt({"exp": T0 + 864000, CLAIM: {"chatgpt_plan_type": "team", "chatgpt_account_id": "ws-1"}})


class ChatGptTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_uses_form_data_and_keeps_id_token(self):
        session = FakeSession(posts=[FakeResponse(200, {
            "access_token": ACCESS_TOKEN, "refresh_token": "r1", "id_token": ID_TOKEN,
        })])
        tokens = await auth.async_exchange_code(session, "c", "s", "v", auth.CHATGPT)
        call = session.post_calls[0]
        self.assertEqual(call["url"], "https://auth.openai.com/oauth/token")
        self.assertIsNone(call["json"])
        self.assertEqual(call["data"]["redirect_uri"], "http://localhost:1455/auth/callback")
        self.assertNotIn("state", call["data"])
        self.assertEqual(tokens.id_token, ID_TOKEN)
        self.assertNotIn("id_token", tokens.as_data())

    async def test_openai_error_objects_are_classified(self):
        for status, expected in ((401, auth.AuthError), (503, auth.TransientError)):
            with self.subTest(status=status):
                session = FakeSession(posts=[FakeResponse(status, {"error": {"code": "token_expired"}})])
                with self.assertRaises(expected):
                    await auth.async_exchange_code(session, "c", "s", "v", auth.CHATGPT)

    async def test_lifetime_comes_from_jwt_without_expires_in(self):
        tokens = auth._token_set({"access_token": ACCESS_TOKEN}, "r", T0)
        self.assertEqual(tokens.expires_at, T0 + 864000)

    async def test_refresh_sends_scope_and_client(self):
        session = FakeSession(posts=[ok_refresh()])
        tm = auth.TokenManager(
            session, auth.TokenSet("a", "old", 0), lambda _: None, clock=lambda: T0, client=auth.CHATGPT
        )
        await tm.async_get_access_token()
        payload = session.post_calls[0]["json"]
        self.assertEqual(payload["client_id"], "app_EMoamEEZ73f0CkXaXp7hrann")
        self.assertEqual(payload["scope"], "openid profile email")

    def test_profile_from_tokens(self):
        profile = api.parse_chatgpt_profile(ID_TOKEN, ACCESS_TOKEN)
        self.assertEqual(profile.account_id, "chatgpt:user-7:ws-1")
        self.assertEqual(profile.workspace_id, "ws-1")
        self.assertEqual(profile.title, "ChatGPT · a@b.c (ChatGPT Team)")
        with self.assertRaises(auth.AuthError):
            api.parse_chatgpt_profile(None, "ikke-en-jwt")

    async def test_usage_sends_workspace_and_retries_401(self):
        session = FakeSession(
            posts=[ok_refresh()],
            gets=[FakeResponse(401), FakeResponse(200, {"rate_limit": {}})],
        )
        tm, _ = manager(session)
        result = await api.ChatGptApi(session, tm, "ws-1").async_get_usage()
        self.assertEqual(result, {"rate_limit": {}})
        self.assertEqual(session.get_calls[1]["url"], "https://chatgpt.com/backend-api/wham/usage")
        self.assertEqual(session.get_calls[1]["headers"]["ChatGPT-Account-Id"], "ws-1")
        self.assertEqual(session.get_calls[1]["headers"]["Authorization"], "Bearer new-access")

    def test_authorize_url_matches_codex(self):
        url = auth.authorize_url("ch", "st", auth.CHATGPT)
        self.assertTrue(url.startswith("https://auth.openai.com/oauth/authorize?"))
        for part in ("codex_cli_simplified_flow=true", "id_token_add_organizations=true",
                     "scope=openid+profile+email+offline_access", "state=st"):
            self.assertIn(part, url)
        self.assertEqual(
            auth.split_pasted_code("http://localhost:1455/auth/callback?code=abc&scope=x&state=st"),
            ("abc", "st"),
        )


class PastedCodeTests(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(auth.split_pasted_code(" abc#xyz "), ("abc", "xyz"))
        self.assertEqual(auth.split_pasted_code("abc"), ("abc", None))
        self.assertEqual(
            auth.split_pasted_code("https://console.anthropic.com/oauth/code/callback?code=abc&state=xyz"),
            ("abc", "xyz"),
        )

    def test_pkce_challenge_is_s256_of_verifier(self):
        import base64
        import hashlib

        verifier, challenge = auth.generate_pkce()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        self.assertIn("scope=user%3Aprofile", auth.authorize_url(challenge, "s"))


if __name__ == "__main__":
    unittest.main()
