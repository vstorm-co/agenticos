"""OAuth 2.1 for the platform's MCP server, end to end against a real database (#2059).

Registration, `/authorize`, the console consent, the code exchange with PKCE, an
MCP call with the token, refresh rotation, and the two thefts RFC 9700 asks a
server to answer: a reused code and a reused refresh token each revoke the grant.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.audit import set_impersonator
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.oauth import OAuthGrant
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.main import app
from app.services.oauth_server import OAuthServerService
from app.services.platform_mcp import serve_platform_mcp

pytestmark = pytest.mark.anyio

REDIRECT = "http://127.0.0.1:33418/callback"


@pytest.fixture
async def served(db: AsyncSession) -> AsyncIterator[None]:
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[deps.get_db_session] = session
    app.dependency_overrides[deps.get_redis] = lambda: MagicMock()
    async with serve_platform_mcp(app, app.state):
        yield
    app.dependency_overrides.clear()


def _http() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


async def _owner(db: AsyncSession) -> AuthContext:
    owner = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(owner)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.commit()
    return AuthContext(user_id=owner.id, organization_id=organization.id, role="owner")


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


async def _register(http: httpx2.AsyncClient, **extra: Any) -> dict[str, Any]:
    response = await http.post(
        "/register",
        json={"redirect_uris": [REDIRECT], "client_name": "Claude Code", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _authorize(http: httpx2.AsyncClient, client_id: str, challenge: str) -> uuid.UUID:
    response = await http.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
        },
    )
    assert response.status_code == 302, response.text
    location = urlparse(response.headers["location"])
    assert location.path == "/oauth/consent"
    return uuid.UUID(parse_qs(location.query)["request"][0])


async def _consent(db: AsyncSession, ctx: AuthContext, request_id: uuid.UUID, *scopes: Perm) -> str:
    answer = await OAuthServerService(db).approve(ctx, request_id, list(scopes))
    await db.commit()
    query = parse_qs(urlparse(answer.redirect_to).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


async def _exchange(
    http: httpx2.AsyncClient, client_id: str, code: str, verifier: str
) -> httpx2.Response:
    return await http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


async def _refresh(http: httpx2.AsyncClient, client_id: str, token: str) -> httpx2.Response:
    return await http.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": token, "client_id": client_id},
    )


async def _whoami(token: str) -> httpx2.Response:
    async with _http() as http:
        return await http.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "whoami", "arguments": {}},
            },
        )


async def _connected(db: AsyncSession, *scopes: Perm) -> tuple[AuthContext, str, dict[str, Any]]:
    ctx = await _owner(db)
    verifier, challenge = _pkce()
    async with _http() as http:
        client = await _register(http)
        request_id = await _authorize(http, client["client_id"], challenge)
        code = await _consent(db, ctx, request_id, *scopes)
        tokens = await _exchange(http, client["client_id"], code, verifier)
    assert tokens.status_code == 200, tokens.text
    return ctx, client["client_id"], tokens.json()


async def test_metadata_points_a_client_at_this_server(served: None) -> None:
    async with _http() as http:
        resource = await http.get("/.well-known/oauth-protected-resource/mcp")
        server = await http.get("/.well-known/oauth-authorization-server")

    assert resource.status_code == 200
    assert server.json()["code_challenge_methods_supported"] == ["S256"]
    assert server.json()["registration_endpoint"].endswith("/register")


async def test_a_consented_client_calls_mcp_as_the_member_within_what_they_granted(
    db: AsyncSession, served: None
) -> None:
    ctx, _client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)

    answer = await _whoami(tokens["access_token"])

    assert tokens["scope"] == "agents:view"
    assert tokens["expires_in"] == 3600
    assert answer.status_code == 200
    assert str(ctx.organization_id) in answer.text
    assert "agents:view" in answer.text


@pytest.mark.security
async def test_a_client_asking_for_a_secret_is_registered_as_public(served: None) -> None:
    async with _http() as http:
        client = await _register(http, token_endpoint_auth_method="client_secret_post")

    assert client["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in client


@pytest.mark.security
async def test_a_wrong_pkce_verifier_gets_no_token(db: AsyncSession, served: None) -> None:
    ctx = await _owner(db)
    _verifier, challenge = _pkce()
    async with _http() as http:
        client = await _register(http)
        request_id = await _authorize(http, client["client_id"], challenge)
        code = await _consent(db, ctx, request_id, Perm.AGENTS_VIEW)
        refused = await _exchange(http, client["client_id"], code, "x" * 64)

    # 401, not RFC 6749's 400: MCP requires it for an invalid grant, and FastMCP's
    # token endpoint answers that way.
    assert refused.status_code == 401
    assert refused.json()["error"] == "invalid_grant"


@pytest.mark.security
async def test_a_reused_code_revokes_the_grant_and_its_tokens(
    db: AsyncSession, served: None
) -> None:
    ctx = await _owner(db)
    verifier, challenge = _pkce()
    async with _http() as http:
        client = await _register(http)
        request_id = await _authorize(http, client["client_id"], challenge)
        code = await _consent(db, ctx, request_id, Perm.AGENTS_VIEW)
        first = await _exchange(http, client["client_id"], code, verifier)
        second = await _exchange(http, client["client_id"], code, verifier)

    assert first.status_code == 200
    assert second.status_code == 401
    assert (await _whoami(first.json()["access_token"])).status_code == 401


@pytest.mark.security
async def test_refresh_rotates_and_a_spent_refresh_token_revokes_everything(
    db: AsyncSession, served: None
) -> None:
    _ctx, client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)

    async with _http() as http:
        rotated = await _refresh(http, client_id, tokens["refresh_token"])
        replayed = await _refresh(http, client_id, tokens["refresh_token"])

    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]
    assert replayed.status_code == 401
    # The theft is answered for both holders: the rotated token dies with the grant.
    assert (await _whoami(rotated.json()["access_token"])).status_code == 401
    async with _http() as http:
        after = await _refresh(http, client_id, rotated.json()["refresh_token"])
    assert after.status_code == 401


async def test_the_client_can_revoke_its_own_access(db: AsyncSession, served: None) -> None:
    _ctx, client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)

    async with _http() as http:
        revoked = await http.post(
            # A public client sends an empty secret: the SDK's request model requires
            # the field to be present.
            "/revoke",
            data={"token": tokens["access_token"], "client_id": client_id, "client_secret": ""},
        )

    assert revoked.status_code == 200
    assert (await _whoami(tokens["access_token"])).status_code == 401


class TestTheConsoleHalf:
    async def test_the_consent_page_names_the_client_and_offers_what_the_member_holds(
        self, db: AsyncSession, served: None
    ) -> None:
        ctx = await _owner(db)
        _verifier, challenge = _pkce()
        async with _http() as http:
            client = await _register(http)
            request_id = await _authorize(http, client["client_id"], challenge)

        page = await OAuthServerService(db).describe(ctx, request_id)

        assert page.client_name == "Claude Code"
        assert page.redirect_host == "127.0.0.1:33418"
        assert page.organization_name == "Acme"
        assert "agents:view" in page.catalog.scopes
        from app.db.models.oauth import OAuthAuthorizationRequest

        pending = (await db.execute(select(OAuthAuthorizationRequest))).scalar_one()
        assert repr(pending).startswith("<OAuthAuthorizationRequest(")

    async def test_denying_tells_the_client_access_denied(
        self, db: AsyncSession, served: None
    ) -> None:
        await _owner(db)
        _verifier, challenge = _pkce()
        async with _http() as http:
            client = await _register(http)
            request_id = await _authorize(http, client["client_id"], challenge)

        answer = await OAuthServerService(db).deny(request_id)

        query = parse_qs(urlparse(answer.redirect_to).query)
        assert query == {"error": ["access_denied"], "state": ["xyz"]}
        with pytest.raises(NotFoundError):
            await OAuthServerService(db).deny(request_id)

    @pytest.mark.security
    async def test_consent_refuses_what_the_member_does_not_hold_and_an_impersonator(
        self, db: AsyncSession, served: None
    ) -> None:
        ctx = await _owner(db)
        member = AuthContext(
            user_id=ctx.user_id, organization_id=ctx.organization_id, role="viewer"
        )
        _verifier, challenge = _pkce()
        async with _http() as http:
            client = await _register(http)
            request_id = await _authorize(http, client["client_id"], challenge)

        with pytest.raises(BadRequestError):
            await OAuthServerService(db).approve(member, request_id, [Perm.AGENTS_EDIT])
        set_impersonator(uuid.uuid4())
        try:
            with pytest.raises(AuthorizationError):
                await OAuthServerService(db).approve(ctx, request_id, [Perm.AGENTS_VIEW])
        finally:
            set_impersonator(None)

    async def test_a_connected_application_is_listed_and_disconnects_with_its_tokens(
        self, db: AsyncSession, served: None
    ) -> None:
        ctx, _client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)
        service = OAuthServerService(db)

        listed = await service.list_grants(ctx)
        await service.disconnect(ctx, listed.items[0].id)
        await db.commit()

        assert [item.client_name for item in listed.items] == ["Claude Code"]
        assert (await service.list_grants(ctx)).items == []
        assert (await _whoami(tokens["access_token"])).status_code == 401
        keys = (await db.execute(select(ApiKey))).scalars().all()
        assert keys and all(key.revoked_at is not None for key in keys)
        with pytest.raises(NotFoundError):
            await service.disconnect(ctx, listed.items[0].id)

    @pytest.mark.security
    async def test_a_member_cannot_disconnect_somebody_else_s_application(
        self, db: AsyncSession, served: None
    ) -> None:
        ctx, _client_id, _tokens = await _connected(db, Perm.AGENTS_VIEW)
        grant = (await db.execute(select(OAuthGrant))).scalar_one()
        stranger = AuthContext(
            user_id=uuid.uuid4(), organization_id=ctx.organization_id, role="member"
        )

        with pytest.raises(NotFoundError):
            await OAuthServerService(db).disconnect(stranger, grant.id)
        assert (await OAuthServerService(db).list_grants(stranger)).items == []


class TestTheServerDirectly:
    """The decisions the SDK's `/token` handler reaches over ASGI, asked directly -
    the coverage tracer loses lines across that hop - and the refusals no client in
    the flows above gets to provoke."""

    async def _granted(self, db: AsyncSession) -> tuple[OAuthServerService, Any, str]:
        ctx = await _owner(db)
        service = OAuthServerService(db)
        await service.register(
            "client-a", {"client_id": "client-a", "client_name": "A", "redirect_uris": [REDIRECT]}
        )
        url = await service.start(
            "client-a",
            {
                "code_challenge": "c" * 43,
                "redirect_uri": REDIRECT,
                "redirect_uri_provided_explicitly": True,
                "state": None,
                "resource": None,
                "scopes": None,
            },
        )
        request_id = uuid.UUID(parse_qs(urlparse(url).query)["request"][0])
        answer = await service.approve(ctx, request_id, [Perm.AGENTS_VIEW])
        code = parse_qs(urlparse(answer.redirect_to).query)["code"][0]
        client = await service.client("client-a")
        return service, client, code

    async def test_codes_and_refresh_tokens_rotate_and_answer_only_their_client(
        self, db: AsyncSession
    ) -> None:
        service, client, code = await self._granted(db)

        assert await service.code("client-b", code) is None
        assert await service.code("client-a", "no-such-code") is None
        found = await service.code("client-a", code)
        assert found is not None and found.redirect_uri == REDIRECT

        issued = await service.exchange_code(client, code)
        assert issued.scopes == ["agents:view"]
        assert await service.refresh("client-b", issued.refresh_token) is None
        assert await service.refresh("client-a", "no-such-token") is None
        renewable = await service.refresh("client-a", issued.refresh_token)
        assert renewable is not None and renewable.scopes == ["agents:view"]

        rotated = await service.exchange_refresh(client, issued.refresh_token, ["agents:view", "x"])
        assert rotated.scopes == ["agents:view"]

        with pytest.raises(NotFoundError):
            await service.exchange_code(client, "no-such-code")
        with pytest.raises(NotFoundError):
            await service.exchange_refresh(client, "no-such-token", [])

    @pytest.mark.security
    async def test_a_spent_code_or_refresh_token_revokes_the_grant(self, db: AsyncSession) -> None:
        service, client, code = await self._granted(db)
        issued = await service.exchange_code(client, code)

        assert await service.code("client-a", code) is None
        grant = (await db.execute(select(OAuthGrant))).scalar_one()
        await db.refresh(grant)
        assert grant.revoked_at is not None
        assert await service.refresh("client-a", issued.refresh_token) is None

    @pytest.mark.security
    async def test_a_rotated_refresh_token_presented_again_revokes_the_live_grant(
        self, db: AsyncSession
    ) -> None:
        service, client, code = await self._granted(db)
        issued = await service.exchange_code(client, code)
        await service.exchange_refresh(client, issued.refresh_token, ["agents:view"])

        assert await service.refresh("client-a", issued.refresh_token) is None
        grant = (await db.execute(select(OAuthGrant))).scalar_one()
        await db.refresh(grant)
        assert grant.revoked_at is not None

    async def test_revoking_through_the_client_ends_the_grant_once(self, db: AsyncSession) -> None:
        service, client, code = await self._granted(db)
        await service.exchange_code(client, code)
        grant = (await db.execute(select(OAuthGrant))).scalar_one()

        await service.revoke_token(grant.id)
        await service.revoke_token(grant.id)
        await service.revoke_token(uuid.uuid4())

        await db.refresh(grant)
        assert grant.revoked_at is not None
        assert repr(grant).startswith("<OAuthGrant(")
        assert repr(client).startswith("<OAuthClient(")
        from app.db.models.oauth import (
            OAuthAuthorizationCode,
            OAuthAuthorizationRequest,
            OAuthRefreshToken,
        )

        for model in (OAuthAuthorizationCode, OAuthAuthorizationRequest, OAuthRefreshToken):
            row = (await db.execute(select(model).limit(1))).scalar_one_or_none()
            assert row is None or repr(row).startswith(f"<{model.__name__}(")

    async def test_an_expired_or_unknown_consent_request_is_not_found(
        self, db: AsyncSession
    ) -> None:
        ctx = await _owner(db)
        with pytest.raises(NotFoundError):
            await OAuthServerService(db).describe(ctx, uuid.uuid4())


class TestTheProviderDirectly:
    async def test_an_unknown_client_or_code_is_a_token_error(
        self, db: AsyncSession, served: None
    ) -> None:
        from mcp.server.auth.provider import TokenError
        from mcp.shared.auth import OAuthClientInformationFull

        from app.services.platform_mcp._oauth import (
            PlatformCode,
            PlatformOAuthProvider,
            PlatformRefreshToken,
        )

        provider = PlatformOAuthProvider()
        ghost = OAuthClientInformationFull(client_id="ghost", redirect_uris=[REDIRECT])
        code = PlatformCode(
            code="nope",
            scopes=[],
            expires_at=0,
            client_id="ghost",
            code_challenge="c",
            redirect_uri=REDIRECT,
            redirect_uri_provided_explicitly=True,
            grant_id=uuid.uuid4(),
        )
        refresh = PlatformRefreshToken(
            token="nope", client_id="ghost", scopes=[], grant_id=uuid.uuid4()
        )
        with pytest.raises(TokenError):
            await provider.exchange_authorization_code(ghost, code)
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(ghost, refresh, [])

        async with _http() as http:
            client = await _register(http)
        known = OAuthClientInformationFull(client_id=client["client_id"], redirect_uris=[REDIRECT])
        with pytest.raises(TokenError) as refused:
            await provider.exchange_authorization_code(known, code)
        assert refused.value.error == "invalid_grant"
        with pytest.raises(TokenError):
            await provider.exchange_refresh_token(known, refresh, [])
        assert await provider.get_client("ghost") is None
        assert await provider.load_authorization_code(known, "nope") is None
        assert await provider.load_refresh_token(known, "nope") is None

    async def test_a_key_a_person_pasted_is_not_revoked_through_oauth(
        self, db: AsyncSession, served: None
    ) -> None:
        from app.services.platform_mcp._oauth import PlatformAccessToken, PlatformOAuthProvider

        await PlatformOAuthProvider().revoke_token(
            PlatformAccessToken(token="aos_x", client_id="aos_x", scopes=[], grant_id=None)
        )


@pytest.mark.security
async def test_two_exchanges_of_one_refresh_token_issue_once_and_revoke(
    db: AsyncSession, served: None
) -> None:
    """Both exchanges loaded the token before either spent it - what two
    concurrent requests do. Only one may issue, and the loser is a reuse."""
    from mcp.server.auth.provider import TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    from app.services.platform_mcp._oauth import PlatformOAuthProvider

    _ctx, client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)
    provider = PlatformOAuthProvider()
    client = OAuthClientInformationFull(client_id=client_id, redirect_uris=[REDIRECT])
    first = await provider.load_refresh_token(client, tokens["refresh_token"])
    second = await provider.load_refresh_token(client, tokens["refresh_token"])
    assert first is not None and second is not None

    issued = await provider.exchange_refresh_token(client, first, [])
    with pytest.raises(TokenError) as lost:
        await provider.exchange_refresh_token(client, second, [])

    assert lost.value.error == "invalid_grant"
    assert (await _whoami(issued.access_token)).status_code == 401


@pytest.mark.security
async def test_a_grant_revoked_after_loading_issues_nothing(db: AsyncSession, served: None) -> None:
    from mcp.server.auth.provider import TokenError
    from mcp.shared.auth import OAuthClientInformationFull

    from app.services.platform_mcp._oauth import PlatformOAuthProvider

    ctx, client_id, tokens = await _connected(db, Perm.AGENTS_VIEW)
    provider = PlatformOAuthProvider()
    client = OAuthClientInformationFull(client_id=client_id, redirect_uris=[REDIRECT])
    loaded = await provider.load_refresh_token(client, tokens["refresh_token"])
    assert loaded is not None
    keys_before = len((await db.execute(select(ApiKey))).scalars().all())

    grant = (await db.execute(select(OAuthGrant))).scalar_one()
    await OAuthServerService(db).disconnect(ctx, grant.id)
    await db.commit()

    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(client, loaded, [])
    db.expire_all()
    assert len((await db.execute(select(ApiKey))).scalars().all()) <= keys_before


@pytest.mark.security
async def test_registration_is_limited_per_address(served: None) -> None:
    """Registering needs no credential; one address may not create rows without end."""
    from unittest.mock import AsyncMock, patch

    from app.services.rate_limit import Decision

    denied = AsyncMock(return_value=Decision(allowed=False, retry_after_seconds=60))
    with patch("app.services.platform_mcp.rate_limit.consume", new=denied):
        async with _http() as http:
            refused = await http.post(
                "/register", json={"redirect_uris": [REDIRECT], "client_name": "flood"}
            )

    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "60"
    assert refused.json()["error"] == "temporarily_unavailable"
    assert denied.await_args.kwargs["surface"] == "oauth_register"


async def test_a_client_nobody_signed_in_with_is_swept_on_the_next_registration(
    db: AsyncSession, served: None
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.models.oauth import OAuthClient

    _ctx, kept_id, _tokens = await _connected(db, Perm.AGENTS_VIEW)
    stale = OAuthClient(
        client_id="stale-client",
        info={"client_id": "stale-client", "redirect_uris": [REDIRECT]},
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    db.add(stale)
    await db.execute(
        OAuthClient.__table__.update()
        .where(OAuthClient.client_id == kept_id)
        .values(created_at=datetime.now(UTC) - timedelta(days=2))
    )
    await db.commit()

    async with _http() as http:
        await _register(http)

    db.expire_all()
    remaining = set((await db.execute(select(OAuthClient.client_id))).scalars())
    assert "stale-client" not in remaining
    assert kept_id in remaining
