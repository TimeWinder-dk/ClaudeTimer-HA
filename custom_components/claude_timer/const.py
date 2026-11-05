"""Konstanter for Claude Timer."""

from __future__ import annotations

DOMAIN = "claude_timer"

# OAuth. Samme offentlige klient som Claude Code bruger; integrationen får sin
# EGEN tilladelse (eget refresh-token) og deler aldrig tokens med Claude Code,
# da refresh-tokens roterer og to klienter ellers logger hinanden ud.
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
OAUTH_SCOPES = "user:profile"

API_BASE_URL = "https://api.anthropic.com"
USAGE_PATH = "/api/oauth/usage"
PROFILE_PATH = "/api/oauth/profile"
API_BETA_HEADER = "oauth-2025-04-20"
REQUEST_TIMEOUT = 20  # sekunder

# Forny adgangstokenet så længe før udløb.
TOKEN_REFRESH_MARGIN = 300  # sekunder

# Polling. Usage-endpointet rate-limiter hårdt (ofte et døgns spærring), så
# minimum er sat konservativt.
DEFAULT_UPDATE_INTERVAL = 300
MIN_UPDATE_INTERVAL = 120
MAX_UPDATE_INTERVAL = 3600
DEFAULT_RATE_LIMIT_BACKOFF = 1800  # sekunder, når 429 ikke har Retry-After
# Hent igen kort efter et vindue er nulstillet, så det nye vindue vises hurtigt.
RESET_REFRESH_DELAY = 30

# Samme niveauer som Windows-appen (UsageLevels).
WARNING_FROM = 50.0
CRITICAL_FROM = 80.0

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_ACCOUNT_ID = "account_id"
CONF_ACCOUNT_NAME = "account_name"
CONF_ACCOUNT_EMAIL = "account_email"
CONF_ORGANIZATION_NAME = "organization_name"
CONF_PLAN = "plan"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_AUTH_CODE = "auth_code"
