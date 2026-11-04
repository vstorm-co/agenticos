"""Who may talk to a Teams bot, and how the bot talks back (#1985).

**Inbound.** Every activity the Bot Connector posts carries a bearer token, and
an activity is believed only once that token checks out: an RS256 signature
against a key the issuer publishes, the issuer itself, an audience that is
*this* bot's app id, a lifetime that has not run out, and - where the token
names one - a `serviceurl` that is the activity's own. The last is what stops a
genuine token for one conversation being replayed with another service's
address, which the bot would then post its answer and its credentials to.

Two issuers sign these. The Bot Framework's own (`https://api.botframework.com`,
keys at `login.botframework.com`) signs what the Connector sends; Entra signs
for a single-tenant registration in the tenant's own name. Each is checked
against its own published keys and its own issuer names - a key from one never
vouches for a token claiming the other.

**Outbound.** The bot answers by calling the Connector with a token from the
tenant it is registered in: the client-credentials grant for its app id and
secret, scoped to the Bot Framework. New bot registrations are single-tenant
since July 2025, so the tenant's own token endpoint is the one to ask.

No SDK. The Bot Framework SDK has been out of support since the end of 2025, and
the wire protocol both it and its successor speak is a JWT check and a handful
of JSON calls.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt

logger = logging.getLogger(__name__)

BOT_FRAMEWORK_ISSUER = "https://api.botframework.com"
BOT_FRAMEWORK_METADATA = "https://login.botframework.com/v1/.well-known/openidconfiguration"
BOT_FRAMEWORK_SCOPE = "https://api.botframework.com/.default"
CLOCK_SKEW_SECONDS = 300
"""The leeway the Bot Framework itself allows a token's times."""

KEYS_TTL_SECONDS = 24 * 3600
"""How long a fetched key set is trusted before it is fetched again.

Microsoft rolls these keys over days, not minutes. A `kid` that is not in the
cached set refetches, so a rotation is picked up on the first token signed with
the new key rather than a day later - at most once per `MISS_COOLDOWN_SECONDS`.
"""

MISS_COOLDOWN_SECONDS = 300
"""The least time between two refetches an unknown `kid` causes.

The key is read before the signature is checked, so anybody who knows a bot's
endpoint can name a fresh `kid` on every request. Without a floor each one cost
two calls to Microsoft, queued behind one lock; with it a flood costs one pair
every five minutes, and a genuine rotation still lands within that.
"""

SERVICE_HOSTS = (
    "smba.trafficmanager.net",
    ".botframework.com",
    ".botframework.us",
    ".teams.microsoft.com",
    ".teams.microsoft.us",
)
"""Where the Bot Connector lives, in the public and the government clouds.

The bot sends its bearer token to the `serviceUrl` an activity names. Even a
verified activity is not a reason to send it anywhere else.
"""


class TeamsAuthError(Exception):
    """An inbound request this bot must not believe. The message says which check failed."""


@dataclass(frozen=True)
class TeamsCredentials:
    """A Teams bot's Azure registration: what it signs in as, where, and its secret.

    Carried through the channel layer as the bot's "token" - one string, like
    every other platform's - so a reply, a prompt and a download each have
    everything they need without a second lookup. `unseal_bot_token` composes it
    from the row; nothing else builds one from text.
    """

    app_id: str
    tenant_id: str
    client_secret: str

    def encode(self) -> str:
        return json.dumps(
            {"app_id": self.app_id, "tenant_id": self.tenant_id, "secret": self.client_secret}
        )

    @classmethod
    def decode(cls, token: str) -> TeamsCredentials:
        """Read what `encode` wrote.

        Raises:
            ValueError: If the string is not one - a Teams bot whose token was
                stored before its registration was, which cannot sign in.
        """
        try:
            data = json.loads(token)
            return cls(
                app_id=str(data["app_id"]),
                tenant_id=str(data["tenant_id"]),
                client_secret=str(data["secret"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("A Teams bot's credentials are not readable") from exc


def is_connector_url(service_url: str) -> bool:
    """Whether `service_url` is a Bot Connector address the bot may send its token to."""
    parsed = urlparse(service_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    # A bare name matches only itself - anybody can create a profile under
    # `trafficmanager.net` - and a leading dot is a domain and its subdomains.
    return any(
        host.endswith(entry) if entry.startswith(".") else host == entry for entry in SERVICE_HOSTS
    )


def _same_service(claimed: str, actual: str) -> bool:
    return claimed.rstrip("/").lower() == actual.rstrip("/").lower()


class _KeySet:
    """One issuer's published signing keys, fetched lazily and refetched on a miss."""

    def __init__(self, metadata_url: str) -> None:
        self.metadata_url = metadata_url
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at = float("-inf")
        self._lock = asyncio.Lock()

    async def key(self, kid: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
        if kid in self._keys and time.monotonic() - self._fetched_at < KEYS_TTL_SECONDS:
            return self._keys[kid]
        async with self._lock:
            # Read again under the lock: a request that waited here behind a
            # refetch finds it done, and does not make its own.
            age = time.monotonic() - self._fetched_at
            if age >= KEYS_TTL_SECONDS or (kid not in self._keys and age >= MISS_COOLDOWN_SECONDS):
                await self._refresh(client)
        return self._keys.get(kid)

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        metadata = (await client.get(self.metadata_url)).raise_for_status().json()
        keys = (await client.get(metadata["jwks_uri"])).raise_for_status().json()
        self._keys = {key["kid"]: key for key in keys.get("keys", []) if "kid" in key}
        self._fetched_at = time.monotonic()


class TeamsAuth:
    """Verifies inbound Bot Connector tokens and mints outbound ones."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._bot_framework = _KeySet(BOT_FRAMEWORK_METADATA)
        self._tenants: dict[str, _KeySet] = {}
        self._tokens: dict[tuple[str, str], tuple[str, float]] = {}
        self._token_lock = asyncio.Lock()

    def _tenant_keys(self, tenant_id: str) -> _KeySet:
        if tenant_id not in self._tenants:
            self._tenants[tenant_id] = _KeySet(
                f"https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
            )
        return self._tenants[tenant_id]

    async def verify(
        self,
        authorization: str | None,
        *,
        app_id: str,
        tenant_id: str,
        service_url: str,
        channel_id: str | None,
    ) -> dict[str, Any]:
        """The token's claims, if it was issued to this bot for this activity.

        Raises:
            TeamsAuthError: Naming the first check that failed - a missing or
                malformed header, an unknown key, a bad signature, the wrong
                issuer, audience or time, or a service address the token does
                not vouch for. The route answers 401 and logs which.
        """
        if not authorization or not authorization.startswith("Bearer "):
            raise TeamsAuthError("no bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        try:
            header = jwt.get_unverified_header(token)
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise TeamsAuthError("a malformed token") from exc
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise TeamsAuthError("a token not signed with RS256 by a named key")

        issuer = unverified.get("iss")
        tenant_issuers = {
            f"https://sts.windows.net/{tenant_id}/",
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        }
        if issuer == BOT_FRAMEWORK_ISSUER:
            keys, issuers = self._bot_framework, [BOT_FRAMEWORK_ISSUER]
        elif issuer in tenant_issuers:
            keys, issuers = self._tenant_keys(tenant_id), sorted(tenant_issuers)
        else:
            raise TeamsAuthError("a token from an issuer this bot does not trust")

        try:
            jwk = await keys.key(header["kid"], self._client)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise TeamsAuthError("the issuer's signing keys could not be read") from exc
        if jwk is None:
            raise TeamsAuthError("a token signed with a key its issuer does not publish")
        endorsements = jwk.get("endorsements")
        if channel_id and isinstance(endorsements, list) and channel_id not in endorsements:
            raise TeamsAuthError("a key not endorsed for this channel")

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                jwt.PyJWK(jwk).key,
                algorithms=["RS256"],
                audience=app_id,
                issuer=issuers,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.InvalidAudienceError as exc:
            raise TeamsAuthError("a token issued to another bot") from exc
        except jwt.InvalidIssuerError as exc:
            raise TeamsAuthError("a token from an issuer this bot does not trust") from exc
        except jwt.ExpiredSignatureError as exc:
            raise TeamsAuthError("an expired token") from exc
        except jwt.PyJWTError as exc:
            raise TeamsAuthError("a token whose signature does not verify") from exc

        claimed = claims.get("serviceurl") or claims.get("serviceUrl")
        if issuer == BOT_FRAMEWORK_ISSUER and not claimed:
            raise TeamsAuthError("a Bot Framework token naming no service")
        if claimed and not _same_service(str(claimed), service_url):
            raise TeamsAuthError("a token issued for another service")
        return claims

    async def access_token(self, credentials: TeamsCredentials) -> str:
        """A token to call the Bot Connector with, cached until shortly before it expires.

        Raises:
            httpx.HTTPStatusError: If Entra refuses the app id or secret.
        """
        cache_key = (credentials.tenant_id, credentials.app_id)
        cached = self._tokens.get(cache_key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
        async with self._token_lock:
            cached = self._tokens.get(cache_key)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]
            response = await self._client.post(
                f"https://login.microsoftonline.com/{credentials.tenant_id}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": credentials.app_id,
                    "client_secret": credentials.client_secret,
                    "scope": BOT_FRAMEWORK_SCOPE,
                },
            )
            if response.is_error:
                # Status only: Entra's error body can echo the client id, and the
                # request carried the secret.
                logger.warning(
                    "teams_token_refused",
                    extra={"status": response.status_code, "app_id": credentials.app_id},
                )
            response.raise_for_status()
            body = response.json()
            token = str(body["access_token"])
            lifetime = int(body.get("expires_in", 3600))
            self._tokens[cache_key] = (token, time.monotonic() + max(lifetime - 300, 60))
            return token
