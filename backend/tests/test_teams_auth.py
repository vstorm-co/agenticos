"""Which Bot Connector tokens a Teams bot believes, and how it signs in to answer (#1985).

A Teams activity is the only thing standing between a stranger and a run on
somebody's budget, so each check the token passes has a refusal here: no header,
a malformed token, a signing key nobody published, a forged signature, a token
for another bot, an expired one, another issuer, a key not endorsed for Teams,
and a token for a different Connector service than the activity names.
"""

import json
import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.channels import teams_auth
from app.services.channels.teams_auth import (
    BOT_FRAMEWORK_ISSUER,
    BOT_FRAMEWORK_METADATA,
    MISS_COOLDOWN_SECONDS,
    TeamsAuth,
    TeamsAuthError,
    TeamsCredentials,
    is_connector_url,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

APP_ID = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
SERVICE = "https://smba.trafficmanager.net/emea/"
BF_KEYS = "https://login.botframework.com/v1/.well-known/keys"
TENANT_METADATA = (
    f"https://login.microsoftonline.com/{TENANT}/v2.0/.well-known/openid-configuration"
)
TENANT_KEYS = f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


SIGNER = _key()
STRANGER = _key()


def _jwk(key: rsa.RSAPrivateKey, kid: str, **extra: Any) -> dict[str, Any]:
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**data, "kid": kid, **extra}


def _pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _token(
    *,
    key: rsa.RSAPrivateKey = SIGNER,
    kid: str = "bf",
    iss: str = BOT_FRAMEWORK_ISSUER,
    aud: str = APP_ID,
    exp_in: int = 3600,
    service: str | None = SERVICE,
    alg: str = "RS256",
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {"iss": iss, "aud": aud, "exp": now + exp_in, "nbf": now - 10}
    if service is not None:
        claims["serviceurl"] = service
    if alg == "HS256":
        return jwt.encode(claims, "x" * 32, algorithm="HS256", headers={"kid": kid})
    return jwt.encode(claims, _pem(key), algorithm=alg, headers={"kid": kid})


def _transport(calls: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        url = str(request.url)
        if url == BOT_FRAMEWORK_METADATA:
            return httpx.Response(200, json={"jwks_uri": BF_KEYS})
        if url == BF_KEYS:
            return httpx.Response(
                200,
                json={
                    "keys": [
                        _jwk(SIGNER, "bf", endorsements=["msteams", "webchat"]),
                        _jwk(SIGNER, "bf-other", endorsements=["skype"]),
                    ]
                },
            )
        if url == TENANT_METADATA:
            return httpx.Response(200, json={"jwks_uri": TENANT_KEYS})
        if url == TENANT_KEYS:
            return httpx.Response(200, json={"keys": [_jwk(SIGNER, "entra")]})
        if url.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "outbound", "expires_in": 3600})
        return httpx.Response(404)

    return httpx.MockTransport(handle)


@pytest.fixture
def auth() -> TeamsAuth:
    return TeamsAuth(httpx.AsyncClient(transport=_transport()))


async def _verify(auth: TeamsAuth, header: str | None, **kwargs: Any) -> dict[str, Any]:
    return await auth.verify(
        header,
        app_id=kwargs.pop("app_id", APP_ID),
        tenant_id=TENANT,
        service_url=kwargs.pop("service_url", SERVICE),
        channel_id=kwargs.pop("channel_id", "msteams"),
    )


class TestATokenThatChecksOut:
    async def test_the_bot_framework_signs_for_its_own_service(self, auth: TeamsAuth) -> None:
        claims = await _verify(auth, f"Bearer {_token()}")
        assert claims["aud"] == APP_ID

    async def test_the_tenant_signs_for_a_single_tenant_bot(self, auth: TeamsAuth) -> None:
        token = _token(kid="entra", iss=f"https://login.microsoftonline.com/{TENANT}/v2.0")
        claims = await _verify(auth, f"Bearer {token}")
        assert claims["iss"].endswith("/v2.0")

    async def test_a_tenant_token_naming_no_service_is_still_believed(
        self, auth: TeamsAuth
    ) -> None:
        token = _token(kid="entra", iss=f"https://sts.windows.net/{TENANT}/", service=None)
        await _verify(auth, f"Bearer {token}")

    async def test_the_trailing_slash_of_a_service_is_not_a_difference(
        self, auth: TeamsAuth
    ) -> None:
        await _verify(auth, f"Bearer {_token()}", service_url=SERVICE.rstrip("/"))

    async def test_keys_are_fetched_once_and_kept(self) -> None:
        calls: list[httpx.Request] = []
        auth = TeamsAuth(httpx.AsyncClient(transport=_transport(calls)))

        await _verify(auth, f"Bearer {_token()}")
        await _verify(auth, f"Bearer {_token()}")

        assert sum(1 for call in calls if str(call.url) == BF_KEYS) == 1

    async def test_unknown_keys_cannot_make_every_request_call_microsoft(self) -> None:
        """A `kid` is read before the signature, so anybody can name a new one (Codex on #2324)."""
        calls: list[httpx.Request] = []
        auth = TeamsAuth(httpx.AsyncClient(transport=_transport(calls)))
        await _verify(auth, f"Bearer {_token()}")

        for n in range(5):
            with pytest.raises(TeamsAuthError, match="does not publish"):
                await _verify(auth, f"Bearer {_token(kid=f'made-up-{n}')}")

        assert sum(1 for call in calls if str(call.url) == BF_KEYS) == 1

    async def test_a_rotated_key_is_fetched_once_the_cooldown_has_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[httpx.Request] = []
        auth = TeamsAuth(httpx.AsyncClient(transport=_transport(calls)))
        await _verify(auth, f"Bearer {_token()}")
        later = time.monotonic() + MISS_COOLDOWN_SECONDS + 1
        monkeypatch.setattr(teams_auth.time, "monotonic", lambda: later)

        with pytest.raises(TeamsAuthError, match="does not publish"):
            await _verify(auth, f"Bearer {_token(kid='rotated')}")

        assert sum(1 for call in calls if str(call.url) == BF_KEYS) == 2


class TestEachCheckRefuses:
    @pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer not-a-jwt"])
    async def test_no_token_or_a_malformed_one(self, auth: TeamsAuth, header: str | None) -> None:
        with pytest.raises(TeamsAuthError):
            await _verify(auth, header)

    async def test_a_token_not_signed_with_rs256(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="RS256"):
            await _verify(auth, f"Bearer {_token(alg='HS256')}")

    async def test_a_key_its_issuer_does_not_publish(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="does not publish"):
            await _verify(auth, f"Bearer {_token(kid='nobody')}")

    async def test_a_forged_signature(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="signature"):
            await _verify(auth, f"Bearer {_token(key=STRANGER)}")

    async def test_a_token_for_another_bot(self, auth: TeamsAuth) -> None:
        other = _token(aud="33333333-3333-3333-3333-333333333333")
        with pytest.raises(TeamsAuthError, match="another bot"):
            await _verify(auth, f"Bearer {other}")

    async def test_an_expired_token(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="expired"):
            await _verify(auth, f"Bearer {_token(exp_in=-3600)}")

    async def test_an_issuer_nobody_trusts(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="issuer"):
            await _verify(auth, f"Bearer {_token(iss='https://evil.example')}")

    async def test_another_tenants_issuer(self, auth: TeamsAuth) -> None:
        token = _token(kid="entra", iss="https://login.microsoftonline.com/other/v2.0")
        with pytest.raises(TeamsAuthError, match="issuer"):
            await _verify(auth, f"Bearer {token}")

    async def test_a_bot_framework_key_vouching_for_a_tenant_token(self, auth: TeamsAuth) -> None:
        """A key from one issuer never vouches for a token claiming the other."""
        token = _token(kid="bf", iss=f"https://sts.windows.net/{TENANT}/")
        with pytest.raises(TeamsAuthError, match="does not publish"):
            await _verify(auth, f"Bearer {token}")

    async def test_a_key_not_endorsed_for_teams(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="endorsed"):
            await _verify(auth, f"Bearer {_token(kid='bf-other')}")

    async def test_a_token_for_another_service(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="another service"):
            await _verify(auth, f"Bearer {_token()}", service_url="https://attacker.example/")

    async def test_a_bot_framework_token_naming_no_service(self, auth: TeamsAuth) -> None:
        with pytest.raises(TeamsAuthError, match="no service"):
            await _verify(auth, f"Bearer {_token(service=None)}")

    async def test_keys_that_cannot_be_read(self) -> None:
        broken = TeamsAuth(
            httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
        )
        with pytest.raises(TeamsAuthError, match="could not be read"):
            await _verify(broken, f"Bearer {_token()}")


class TestSigningInToAnswer:
    async def test_a_token_is_asked_for_once_and_reused(self) -> None:
        calls: list[httpx.Request] = []
        auth = TeamsAuth(httpx.AsyncClient(transport=_transport(calls)))
        credentials = TeamsCredentials(APP_ID, TENANT, "secret")

        assert await auth.access_token(credentials) == "outbound"
        assert await auth.access_token(credentials) == "outbound"

        (asked,) = [call for call in calls if "oauth2" in str(call.url)]
        assert TENANT in str(asked.url)
        body = dict(httpx.QueryParams(asked.content.decode()))
        assert body["scope"] == "https://api.botframework.com/.default"
        assert body["client_id"] == APP_ID

    async def test_a_refused_secret_raises(self) -> None:
        auth = TeamsAuth(
            httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(401)))
        )
        with pytest.raises(httpx.HTTPStatusError):
            await auth.access_token(TeamsCredentials(APP_ID, TENANT, "wrong"))


class TestCredentials:
    def test_they_survive_the_trip_through_one_string(self) -> None:
        credentials = TeamsCredentials(APP_ID, TENANT, "s3cret")
        assert TeamsCredentials.decode(credentials.encode()) == credentials

    @pytest.mark.parametrize("token", ["xoxb-a-slack-token", "{}", "[1]"])
    def test_anything_else_is_refused(self, token: str) -> None:
        with pytest.raises(ValueError, match="not readable"):
            TeamsCredentials.decode(token)


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://smba.trafficmanager.net/emea/", True),
        ("https://smba.infra.gcc.teams.microsoft.com/gcc/", True),
        ("https://api.botframework.com/", True),
        ("https://evilsmba.trafficmanager.net/", False),
        ("https://smba.trafficmanager.net.evil.example/", False),
        ("http://smba.trafficmanager.net/", False),
        ("https://attacker.example/", False),
        ("not a url", False),
    ],
)
def test_the_token_is_only_ever_sent_to_a_connector(url: str, allowed: bool) -> None:
    assert is_connector_url(url) is allowed
