"""Tests for MCP connections: agents/mcp toolset building + the service layer."""

import contextlib
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from mcp.shared.auth import OAuthMetadata, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.exc import IntegrityError

from app.agents import mcp_oauth
from app.agents.mcp import (
    McpProbeError,
    McpServerSpec,
    McpToolInfo,
    _make_toolset,
    _mcp_transport,
    _tool_prefix,
    build_mcp_toolsets,
    probe_mcp_server,
)
from app.agents.mcp_oauth import McpOAuthPayload
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.pinned_http import PinnedAsyncClient
from app.core.vault import VaultScope, seal, unseal
from app.db.models.mcp_connection import McpConnection
from app.schemas.mcp_connection import (
    McpConnectionCreate,
    McpConnectionRead,
    McpConnectionUpdate,
    OrgMcpConnectionCreate,
    OrgMcpConnectionRead,
    OrgMcpConnectionUpdate,
)
from app.services import mcp_connection as mcp_connection_service
from app.services.mcp_connection import (
    McpConnectionService,
    _apply_token,
    _resolve_auth_headers,
    connection_scope,
)


@contextlib.asynccontextmanager
async def _acm(value):
    """Minimal async context manager yielding *value* (fakes a transport client)."""
    yield value


def _allow_any_url(monkeypatch) -> None:
    """Skip SSRF validation for tests that are about something else (it resolves
    DNS, so it must not run against made-up hostnames)."""

    async def _passthrough(url: str) -> str:
        return url

    monkeypatch.setattr(mcp_connection_service, "validate_mcp_url", _passthrough)


def _connection(**overrides) -> McpConnection:
    defaults: dict = {
        "id": uuid4(),
        "user_id": uuid4(),
        "organization_id": None,
        "created_by_user_id": None,
        # Personal unless a test says otherwise - an in-memory row gets no
        # column default, and a scope of None would fail every ownership check
        # for a reason that has nothing to do with what the test is about.
        "scope": "user",
        "catalog_key": None,
        "name": "github",
        "url": "https://example.com/mcp",
        "auth_token": None,
        "secret_key_version": 1,
        "allowed_tools": None,
        "is_enabled": True,
        "auth_type": "bearer",
        "oauth_state": None,
        "oauth_payload": None,
        "oauth_pending_payload": None,
        "last_status": None,
        "last_error": None,
        "last_checked_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": None,
    }
    defaults.update(overrides)
    conn = McpConnection()
    for key, value in defaults.items():
        setattr(conn, key, value)
    return conn


def _seal_into(conn: McpConnection, plaintext: str) -> str:
    """Seal a value for this row's owner, exactly as the service would.

    Sealing depends on the row, so a fixture cannot prepare a ciphertext before
    the row exists - which is the whole point: a personal token is bound to the
    member, an organization one to the organization.
    """
    return seal(
        plaintext, scope=connection_scope(conn), key_version=conn.secret_key_version
    ).ciphertext


def _open_from(conn: McpConnection, ciphertext: str) -> str:
    return unseal(ciphertext, scope=connection_scope(conn), key_version=conn.secret_key_version)


class TestToolPrefix:
    def test_hyphens_become_underscores(self):
        assert _tool_prefix("github-work") == "github_work"

    def test_uppercase_and_specials_are_sanitized(self):
        assert _tool_prefix("My Server!") == "my_server"

    def test_empty_falls_back(self):
        assert _tool_prefix("!!!") == "mcp"


class TestTransportSelection:
    """`_mcp_transport` must pick SSE vs streamable HTTP from the URL alone."""

    @pytest.mark.anyio
    async def test_sse_url_uses_sse_client(self, monkeypatch):
        calls: list = []
        import mcp.client.sse as sse_mod

        def sse_client(url, headers=None):
            calls.append(("sse", url, headers))
            return _acm(("sse-read", "sse-write"))

        monkeypatch.setattr(sse_mod, "sse_client", sse_client)
        async with _mcp_transport("https://mcp.atlassian.com/v1/sse", {"h": "1"}) as (r, w):
            assert (r, w) == ("sse-read", "sse-write")
        assert calls == [("sse", "https://mcp.atlassian.com/v1/sse", {"h": "1"})]

    @pytest.mark.anyio
    async def test_http_url_uses_streamable_client(self, monkeypatch):
        calls: list = []
        import mcp.client.streamable_http as http_mod

        def streamablehttp_client(url, headers=None):
            calls.append(("http", url, headers))
            return _acm(("http-read", "http-write", lambda: None))

        monkeypatch.setattr(http_mod, "streamablehttp_client", streamablehttp_client)
        async with _mcp_transport("https://example.com/mcp", None) as (r, w):
            assert (r, w) == ("http-read", "http-write")
        assert calls == [("http", "https://example.com/mcp", None)]


class TestMakeToolset:
    def test_without_allowlist_returns_prefixed_server(self):
        from pydantic_ai.mcp import MCPToolset
        from pydantic_ai.toolsets import PrefixedToolset

        spec = McpServerSpec(name="github-work", url="https://example.com/mcp")
        toolset = _make_toolset(spec)
        assert isinstance(toolset, PrefixedToolset)
        assert toolset.prefix == "github_work"
        assert isinstance(toolset.wrapped, MCPToolset)

    def test_with_allowlist_filters_before_prefixing(self):
        from pydantic_ai.toolsets import FilteredToolset, PrefixedToolset

        spec = McpServerSpec(
            name="github",
            url="https://example.com/mcp",
            allowed_tools=["search_issues"],
        )
        toolset = _make_toolset(spec)
        assert isinstance(toolset, PrefixedToolset)
        filtered = toolset.wrapped
        assert isinstance(filtered, FilteredToolset)
        # The filter runs before prefixing → unprefixed names.
        allowed_tool = MagicMock()
        allowed_tool.name = "search_issues"
        blocked_tool = MagicMock()
        blocked_tool.name = "delete_repo"
        assert filtered.filter_func(None, allowed_tool) is True
        assert filtered.filter_func(None, blocked_tool) is False


class TestBuildMcpToolsets:
    @pytest.mark.anyio
    async def test_empty_specs_no_probing(self):
        assert await build_mcp_toolsets([]) == []

    @pytest.mark.anyio
    async def test_unreachable_server_is_skipped(self, monkeypatch):
        async def failing_probe(url, headers=None, timeout=None):
            raise TimeoutError("no route")

        monkeypatch.setattr("app.agents.mcp.probe_mcp_server", failing_probe)
        specs = [McpServerSpec(name="dead", url="https://example.com/mcp")]
        assert await build_mcp_toolsets(specs) == []

    @pytest.mark.anyio
    async def test_reachable_server_yields_toolset(self, monkeypatch):
        async def ok_probe(url, headers=None, timeout=None):
            return [McpToolInfo(name="t", description="")]

        monkeypatch.setattr("app.agents.mcp.probe_mcp_server", ok_probe)
        specs = [McpServerSpec(name="live", url="https://example.com/mcp")]
        toolsets = await build_mcp_toolsets(specs)
        assert len(toolsets) == 1

    @pytest.mark.anyio
    async def test_colliding_tool_prefix_is_dropped(self, monkeypatch):
        """Two servers sharing a prefix would make pydantic-ai raise on
        duplicate tool names and kill the turn - the later one is skipped."""
        probed: list[str] = []

        async def ok_probe(url, headers=None, timeout=None):
            probed.append(url)
            return [McpToolInfo(name="t", description="")]

        monkeypatch.setattr("app.agents.mcp.probe_mcp_server", ok_probe)
        specs = [
            # Workspace server first - it wins over the user's connection.
            McpServerSpec(name="github", url="https://workspace.example/mcp"),
            McpServerSpec(name="GitHub", url="https://user.example/mcp"),
        ]
        toolsets = await build_mcp_toolsets(specs)
        assert len(toolsets) == 1
        assert probed == ["https://workspace.example/mcp"]


class TestProbeSuccess:
    @pytest.mark.anyio
    async def test_a_reachable_server_lists_its_tools(self, monkeypatch):
        """The probe's whole product: the tool names an admin picks from,
        with a missing description read as empty rather than None."""
        described = MagicMock(description="Search issues")
        described.name = "search"
        bare = MagicMock(description=None)
        bare.name = "create_issue"
        session = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock(tools=[described, bare]))

        monkeypatch.setattr(
            "app.agents.mcp._mcp_transport",
            lambda url, headers: _acm((MagicMock(), MagicMock())),
        )
        monkeypatch.setattr("mcp.ClientSession", lambda read, write: _acm(session))

        tools = await probe_mcp_server("https://example.com/mcp")

        assert tools == [
            McpToolInfo(name="search", description="Search issues"),
            McpToolInfo(name="create_issue", description=""),
        ]
        session.initialize.assert_awaited_once()


class TestProbeErrors:
    """A dead server must never abort the turn - including when the failure
    arrives as an exception group out of the anyio task group."""

    @pytest.mark.anyio
    async def test_exception_group_becomes_probe_error(self, monkeypatch):
        @contextlib.asynccontextmanager
        async def failing_transport(url, headers):
            raise BaseExceptionGroup("unhandled errors in a TaskGroup", [ConnectionError("boom")])
            yield  # pragma: no cover

        monkeypatch.setattr("app.agents.mcp._mcp_transport", failing_transport)
        # McpProbeError is an Exception, so `except Exception` callers catch it.
        with pytest.raises(McpProbeError, match="boom"):
            await probe_mcp_server("https://example.com/mcp")

    @pytest.mark.anyio
    async def test_cancellation_is_not_swallowed(self, monkeypatch):
        import asyncio

        @contextlib.asynccontextmanager
        async def cancelled_transport(url, headers):
            raise BaseExceptionGroup("cancelled", [asyncio.CancelledError()])
            yield  # pragma: no cover

        monkeypatch.setattr("app.agents.mcp._mcp_transport", cancelled_transport)
        with pytest.raises(BaseExceptionGroup):
            await probe_mcp_server("https://example.com/mcp")


class TestToolsetsForAgent:
    """What a *published* agent reaches: the servers its spec named, nothing else.

    An agent that picked up whatever the person triggering it had enabled would
    answer differently depending on who asked, and would run on that person's
    tokens.
    """

    @staticmethod
    def _capture(monkeypatch) -> list[list[McpServerSpec]]:
        """Replace the toolset build with a recorder of the specs it was given."""
        seen: list[list[McpServerSpec]] = []

        async def fake_build(specs: list[McpServerSpec]) -> list[str]:
            seen.append(specs)
            return [spec.name for spec in specs]

        monkeypatch.setattr(mcp_connection_service, "build_mcp_toolsets", fake_build)
        return seen

    @pytest.mark.anyio
    async def test_only_the_servers_the_spec_names_are_attached(self, monkeypatch):
        """The deployment's own MCP_SERVERS are ambient config nobody bound here.

        Including them would put tools in a published agent that its spec does
        not mention and that publish-time validation never checked.
        """
        seen = self._capture(monkeypatch)
        bound = _connection(name="linear", url="https://mcp.linear.app/sse")
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(return_value=bound),
        )

        toolsets = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=uuid4(), connection_ids=[bound.id]
        )

        assert toolsets == ["linear"]
        assert [spec.name for spec in seen[0]] == ["linear"]

    @pytest.mark.anyio
    async def test_every_id_is_resolved_inside_the_agents_own_organization(self, monkeypatch):
        """A spec is data and can name any UUID; the tenant it resolves in is not
        negotiable, and neither is the connection being an organization one."""
        self._capture(monkeypatch)
        organization_id = uuid4()
        connection_id = uuid4()
        lookup = AsyncMock(return_value=_connection(id=connection_id))
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo, "get_org_scoped_by_id", lookup
        )

        await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=organization_id, connection_ids=[connection_id]
        )

        assert lookup.await_args.kwargs == {
            "connection_id": connection_id,
            "organization_id": organization_id,
        }

    @pytest.mark.anyio
    async def test_the_allowlist_the_admin_picked_travels_with_the_server(self, monkeypatch):
        """An agent must not reach tools somebody deliberately excluded."""
        seen = self._capture(monkeypatch)
        bound = _connection(name="github", allowed_tools=["search_issues"])
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(return_value=bound),
        )

        await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=uuid4(), connection_ids=[bound.id]
        )

        assert seen[0][0].allowed_tools == ["search_issues"]

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("connection", "reason"),
        [
            (None, "deleted, or moved out of the organization, after publish"),
            (_connection(is_enabled=False), "switched off by an administrator"),
        ],
    )
    async def test_a_binding_that_no_longer_resolves_narrows_the_agent_rather_than_failing_the_run(
        self, monkeypatch, connection, reason
    ):
        """Same call as :meth:`AgentRunnerService._collection_names` makes for a
        deleted collection: the answer gets worse, it does not disappear. What
        refuses a broken binding is publish, while somebody can still fix it."""
        seen = self._capture(monkeypatch)
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(return_value=connection),
        )

        toolsets = await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=uuid4(), connection_ids=[uuid4()]
        )

        assert toolsets == []
        assert seen[0] == []

    @pytest.mark.anyio
    async def test_a_server_whose_credentials_are_unusable_is_dropped_not_sent_unauthenticated(
        self, monkeypatch
    ):
        """An expired OAuth grant or a rotated SECRET_KEY must not become an
        anonymous request to somebody's Linear workspace."""
        seen = self._capture(monkeypatch)
        broken = _connection(name="linear", auth_token="enc:not-valid-ciphertext")
        healthy = _connection(name="github")
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_org_scoped_by_id",
            AsyncMock(side_effect=[broken, healthy]),
        )

        await mcp_connection_service.build_toolsets_for_agent(
            AsyncMock(), organization_id=uuid4(), connection_ids=[broken.id, healthy.id]
        )

        assert [spec.name for spec in seen[0]] == ["github"]


class TestAuthHeaders:
    @pytest.mark.anyio
    async def test_no_token_no_headers(self):
        assert await _resolve_auth_headers(AsyncMock(), _connection()) == {}

    @pytest.mark.anyio
    async def test_token_is_decrypted_into_bearer_header(self):
        conn = _connection()
        conn.auth_token = _seal_into(conn, "secret-token")
        assert await _resolve_auth_headers(AsyncMock(), conn) == {
            "Authorization": "Bearer secret-token"
        }

    @pytest.mark.anyio
    async def test_another_members_envelope_does_not_open(self):
        """A personal token is bound to its owner, not to the deployment.

        This is the property the old global Fernet key could not give: a
        ciphertext lifted out of one member's row and dropped into another's
        decrypted happily, and it is somebody's live credential for a third-party
        service.
        """
        mine = _connection()
        stolen = _connection(auth_token=_seal_into(mine, "secret-token"))
        assert await _resolve_auth_headers(AsyncMock(), stolen) is None

    @pytest.mark.anyio
    async def test_a_personal_row_without_an_owner_is_refused_not_guessed(self):
        """The mirror of the organization case, and equally unreachable by API."""
        conn = _connection(user_id=None, auth_token="whatever")

        with pytest.raises(BadRequestError, match="no owner"):
            connection_scope(conn)

    @pytest.mark.anyio
    async def test_undecryptable_token_yields_none(self):
        conn = _connection(auth_token="enc:not-valid-ciphertext")
        assert await _resolve_auth_headers(AsyncMock(), conn) is None

    @pytest.mark.anyio
    async def test_an_organization_token_is_opened_with_the_organizations_envelope(self):
        organization_id = uuid4()
        sealed = seal("org-token", scope=VaultScope.organization(organization_id))
        conn = _connection(
            scope="org",
            user_id=None,
            organization_id=organization_id,
            auth_token=sealed.ciphertext,
            secret_key_version=sealed.key_version,
        )
        assert await _resolve_auth_headers(AsyncMock(), conn) == {
            "Authorization": "Bearer org-token"
        }

    @pytest.mark.anyio
    async def test_another_organizations_envelope_does_not_open(self):
        """The vault binds a ciphertext to the organization it was sealed for.
        A row copied between tenants - by a bad restore, or by hand - must be
        unusable rather than silently working somewhere it does not belong."""
        sealed = seal("org-token", scope=VaultScope.organization(uuid4()))
        conn = _connection(
            scope="org",
            user_id=None,
            organization_id=uuid4(),
            auth_token=sealed.ciphertext,
            secret_key_version=sealed.key_version,
        )
        assert await _resolve_auth_headers(AsyncMock(), conn) is None

    @pytest.mark.anyio
    async def test_an_organization_row_without_an_organization_is_refused_not_guessed(self):
        """A check constraint makes this unreachable through the API, so hitting
        it means the data is corrupt. Falling through to the deployment key
        would report "wrong master key" about a row never sealed with one."""
        conn = _connection(scope="org", user_id=None, organization_id=None, auth_token="whatever")

        with pytest.raises(BadRequestError, match="no organization"):
            connection_scope(conn)


def _oauth_connection(payload: McpOAuthPayload, **overrides) -> McpConnection:
    """A connection carrying a sealed OAuth payload."""
    conn = _connection(auth_type="oauth", **overrides)
    conn.oauth_payload = _seal_into(conn, payload.model_dump_json())
    return conn


def _base_payload(**overrides) -> McpOAuthPayload:
    data = {
        "server_url": "https://srv/mcp",
        "started_at": datetime.now(UTC).timestamp(),
        "authorization_endpoint": "https://srv/authorize",
        "token_endpoint": "https://srv/token",
        "client_id": "cid",
        "client_secret": "csecret",
        "scope": "read",
        "resource": "https://srv/mcp",
        "redirect_uri": "https://app/api/me/mcp-connections/oauth/callback",
    }
    data.update(overrides)
    return McpOAuthPayload(**data)


class TestOAuthTokens:
    def test_apply_token_folds_grant(self):
        payload = _base_payload(code_verifier="verifier", refresh_token="old-refresh")
        token = OAuthToken(access_token="AT", refresh_token="new-refresh", expires_in=3600)
        result = _apply_token(payload, token)
        assert result.access_token == "AT"
        assert result.refresh_token == "new-refresh"
        assert result.code_verifier is None  # cleared once tokens arrive
        assert (
            result.expires_at is not None and result.expires_at > mcp_oauth.TOKEN_EXPIRY_SKEW_SECS
        )

    def test_apply_token_keeps_refresh_when_omitted(self):
        payload = _base_payload(refresh_token="keep-me")
        token = OAuthToken(access_token="AT", expires_in=None)
        result = _apply_token(payload, token)
        assert result.refresh_token == "keep-me"
        assert result.expires_at is None

    @pytest.mark.anyio
    async def test_unauthorized_oauth_yields_none(self):
        # No access_token yet (consent not completed).
        conn = _oauth_connection(_base_payload(code_verifier="v"), oauth_state="state123")
        assert await _resolve_auth_headers(AsyncMock(), conn) is None

    @pytest.mark.anyio
    async def test_valid_oauth_token_becomes_bearer(self):
        payload = _base_payload(access_token="live-token", expires_at=None)
        conn = _oauth_connection(payload)
        assert await _resolve_auth_headers(AsyncMock(), conn) == {
            "Authorization": "Bearer live-token"
        }

    @pytest.mark.anyio
    async def test_expired_token_is_refreshed_and_persisted(self, monkeypatch):
        payload = _base_payload(
            access_token="stale", refresh_token="rt", expires_at=0.0
        )  # long expired
        conn = _oauth_connection(payload)
        fresh = OAuthToken(access_token="fresh-token", refresh_token="rt2", expires_in=3600)
        refresh_mock = AsyncMock(return_value=fresh)
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", refresh_mock)
        lock_mock = AsyncMock(return_value=conn)
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo, "get_by_id_for_update", lock_mock
        )
        update_mock = AsyncMock()
        monkeypatch.setattr(mcp_connection_service.mcp_connection_repo, "update", update_mock)

        headers = await _resolve_auth_headers(AsyncMock(), conn)
        assert headers == {"Authorization": "Bearer fresh-token"}
        refresh_mock.assert_awaited_once()
        # The refresh token is only ever spent while holding the row lock.
        lock_mock.assert_awaited_once()
        # The refreshed token was persisted back (re-encrypted).
        stored = update_mock.call_args.kwargs["update_data"]["oauth_payload"]
        assert McpOAuthPayload.model_validate_json(_open_from(conn, stored)).access_token == (
            "fresh-token"
        )

    @pytest.mark.anyio
    async def test_concurrent_turn_reuses_the_token_the_winner_stored(self, monkeypatch):
        """Two turns can hit an expired token at once. The one that loses the
        row lock must re-read the row and use the fresh token, not spend the
        refresh token a second time - providers that rotate it would invalidate
        the winner's copy and quietly kill the connection."""
        stale = _oauth_connection(
            _base_payload(access_token="stale", refresh_token="rt", expires_at=0.0)
        )
        # What the winner committed while we waited on the lock.
        refreshed = _oauth_connection(
            _base_payload(
                access_token="fresh-token",
                refresh_token="rt2",
                expires_at=datetime.now(UTC).timestamp() + 3600,
            )
        )
        refresh_mock = AsyncMock()
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", refresh_mock)
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_by_id_for_update",
            AsyncMock(return_value=refreshed),
        )
        update_mock = AsyncMock()
        monkeypatch.setattr(mcp_connection_service.mcp_connection_repo, "update", update_mock)

        headers = await _resolve_auth_headers(AsyncMock(), stale)

        assert headers == {"Authorization": "Bearer fresh-token"}
        refresh_mock.assert_not_awaited()
        update_mock.assert_not_awaited()

    @pytest.mark.anyio
    async def test_expired_token_without_refresh_yields_none(self):
        payload = _base_payload(access_token="stale", refresh_token=None, expires_at=0.0)
        conn = _oauth_connection(payload)
        assert await _resolve_auth_headers(AsyncMock(), conn) is None

    @pytest.mark.anyio
    async def test_a_connection_awaiting_first_consent_has_no_payload_to_read(self):
        """`oauth_start` writes the row before the user ever sees the consent
        screen, so `oauth_payload` is NULL rather than unreadable. That is not
        a licence to reach the server anonymously - the plugin is simply not
        usable until the callback lands."""
        conn = _connection(auth_type="oauth", oauth_payload=None, oauth_state="pending")
        assert await _resolve_auth_headers(AsyncMock(), conn) is None


class TestRefreshUnderLock:
    """What happens between finding an expired token and spending the refresh one.

    Every case here ends in `None`, and the reason is the same each time: a
    turn that loses one server is a worse answer, while a refresh token redeemed
    against the wrong copy of the row is a connection the user has to notice is
    broken and re-authorize by hand. When the locked row disagrees with the copy
    read before the lock, the locked row is the one that is true.
    """

    @staticmethod
    def _expired() -> McpConnection:
        """The pre-lock copy: expired access token, refresh token still there."""
        return _oauth_connection(
            _base_payload(access_token="stale", refresh_token="rt", expires_at=0.0)
        )

    @staticmethod
    def _locked(monkeypatch, row: McpConnection | None) -> AsyncMock:
        """What `SELECT ... FOR UPDATE` finds once the lock is granted."""
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_by_id_for_update",
            AsyncMock(return_value=row),
        )
        refresh = AsyncMock()
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", refresh)
        return refresh

    @pytest.mark.anyio
    async def test_a_connection_deleted_while_the_turn_waited_is_not_refreshed(self, monkeypatch):
        """Deleting a connection is how a user revokes it. If the lock is granted
        only after the row is gone, spending its refresh token would hand the
        provider a credential the user has just withdrawn."""
        refresh = self._locked(monkeypatch, None)

        assert await _resolve_auth_headers(AsyncMock(), self._expired()) is None
        refresh.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_payload_cleared_under_the_lock_is_not_refreshed_from_the_stale_copy(
        self, monkeypatch
    ):
        """Moving a connection's URL wipes `oauth_payload`, because tokens
        belong to the host that issued them. A turn holding the pre-lock copy
        must not resurrect them against the new host."""
        refresh = self._locked(monkeypatch, _connection(auth_type="oauth", oauth_payload=None))

        assert await _resolve_auth_headers(AsyncMock(), self._expired()) is None
        refresh.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_refresh_token_the_locked_row_no_longer_has_is_not_spent(self, monkeypatch):
        """The winner of the lock may have stored a grant that came back without
        a refresh token. Falling back to the one in the stale copy would redeem
        a token the provider already rotated away, and providers answer that by
        invalidating the whole grant."""
        refresh = self._locked(
            monkeypatch,
            _oauth_connection(
                _base_payload(access_token="stale", refresh_token=None, expires_at=0.0)
            ),
        )

        assert await _resolve_auth_headers(AsyncMock(), self._expired()) is None
        refresh.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_provider_refusing_the_refresh_drops_the_server_without_writing_anything(
        self, monkeypatch
    ):
        """A revoked grant is fixed by re-authorizing, not by failing the chat
        turn. Nothing is persisted either: overwriting the payload would destroy
        the record of what the user needs to re-authorize."""
        monkeypatch.setattr(
            mcp_connection_service.mcp_connection_repo,
            "get_by_id_for_update",
            AsyncMock(return_value=self._expired()),
        )
        monkeypatch.setattr(
            mcp_oauth,
            "refresh_tokens",
            AsyncMock(side_effect=mcp_oauth.OAuthError("invalid_grant")),
        )
        update = AsyncMock()
        monkeypatch.setattr(mcp_connection_service.mcp_connection_repo, "update", update)

        assert await _resolve_auth_headers(AsyncMock(), self._expired()) is None
        update.assert_not_awaited()


class TestOAuthSweep:
    """The scheduled pass over every OAuth connection on the deployment.

    It exists for one failure the lazy refresh cannot report: a refresh token
    the provider has revoked is otherwise discovered by an agent, mid-run, in
    front of whoever asked the question. So the two things worth guarding are
    that a dead grant is written down *before* anybody's run hits it, and that
    a healthy fleet is left alone - this runs on a schedule over rows belonging
    to every tenant, and a write per connection per pass would be both noise
    and a claim nobody checked.
    """

    @pytest.fixture
    def repo(self, monkeypatch):
        mock_repo = MagicMock()
        mock_repo.list_oauth_connections = AsyncMock(return_value=[])
        mock_repo.get_by_id_for_update = AsyncMock()
        mock_repo.update = AsyncMock()
        monkeypatch.setattr(mcp_connection_service, "mcp_connection_repo", mock_repo)
        return mock_repo

    @staticmethod
    def _written(repo) -> dict:
        """The status the sweep recorded - the last write, after any re-seal."""
        return repo.update.await_args.kwargs["update_data"]

    @pytest.mark.anyio
    async def test_a_connection_nobody_has_authorized_is_not_reported_as_expired(
        self, repo, monkeypatch
    ):
        """Two rows reach here with nothing to refresh: one whose consent was
        never completed, and one whose payload this deployment can no longer
        decrypt. Marking either "Authorization expired" would send somebody to
        reconnect a plugin over a fact the sweep did not establish."""
        never_authorized = _oauth_connection(_base_payload(code_verifier="v"))
        unreadable = _connection(auth_type="oauth", oauth_payload="enc:not-valid-ciphertext")
        repo.list_oauth_connections.return_value = [never_authorized, unreadable]
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", AsyncMock())

        counts = await mcp_connection_service.sweep_oauth_connections(AsyncMock())

        assert counts == {"checked": 0, "refreshed": 0, "needs_authorization": 0, "skipped": 2}
        repo.update.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_token_that_is_still_good_is_counted_and_left_alone(self, repo, monkeypatch):
        """The lazy refresh renews a token at the moment it is needed, which no
        schedule beats. A sweep that renewed early would spend a refresh token
        for nothing, and one that wrote `last_checked_at` anyway would cost a
        write per connection per pass to say what it already said."""
        healthy = _oauth_connection(
            _base_payload(access_token="live", expires_at=datetime.now(UTC).timestamp() + 3600)
        )
        repo.list_oauth_connections.return_value = [healthy]
        refresh = AsyncMock()
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", refresh)

        counts = await mcp_connection_service.sweep_oauth_connections(AsyncMock())

        assert counts == {"checked": 1, "refreshed": 0, "needs_authorization": 0, "skipped": 1}
        refresh.assert_not_awaited()
        repo.update.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_token_about_to_expire_is_renewed_and_the_row_marked_healthy(
        self, repo, monkeypatch
    ):
        expiring = _oauth_connection(
            _base_payload(access_token="stale", refresh_token="rt", expires_at=0.0)
        )
        repo.list_oauth_connections.return_value = [expiring]
        repo.get_by_id_for_update.return_value = expiring
        monkeypatch.setattr(
            mcp_oauth,
            "refresh_tokens",
            AsyncMock(return_value=OAuthToken(access_token="fresh", expires_in=3600)),
        )

        counts = await mcp_connection_service.sweep_oauth_connections(AsyncMock())

        assert counts == {"checked": 1, "refreshed": 1, "needs_authorization": 0, "skipped": 0}
        written = self._written(repo)
        assert (written["last_status"], written["last_error"]) == ("ok", None)
        assert written["last_checked_at"] is not None

    @pytest.mark.anyio
    async def test_a_grant_the_provider_has_revoked_is_written_down_before_a_run_finds_it(
        self, repo, monkeypatch
    ):
        """The whole reason this flow exists. Withdrawing the grant in the
        provider's console leaves a connection that still looks fine until an
        agent reaches for it mid-conversation; the sweep is what puts "needs
        authorization" in front of somebody who can act on it."""
        revoked = _oauth_connection(
            _base_payload(access_token="stale", refresh_token="rt", expires_at=0.0)
        )
        repo.list_oauth_connections.return_value = [revoked]
        repo.get_by_id_for_update.return_value = revoked
        monkeypatch.setattr(
            mcp_oauth,
            "refresh_tokens",
            AsyncMock(side_effect=mcp_oauth.OAuthError("invalid_grant")),
        )

        counts = await mcp_connection_service.sweep_oauth_connections(AsyncMock())

        assert counts == {"checked": 1, "refreshed": 0, "needs_authorization": 1, "skipped": 0}
        written = self._written(repo)
        assert written["last_status"] == "error"
        assert "reconnect" in written["last_error"]

    @pytest.mark.anyio
    async def test_an_expired_token_with_no_refresh_path_is_marked_without_taking_a_lock(
        self, repo, monkeypatch
    ):
        """A grant issued without a refresh token cannot be renewed by anybody.
        Taking the row lock to discover that would make the sweep contend with
        live chat turns for every one of them."""
        stranded = _oauth_connection(
            _base_payload(access_token="stale", refresh_token=None, expires_at=0.0)
        )
        repo.list_oauth_connections.return_value = [stranded]
        refresh = AsyncMock()
        monkeypatch.setattr(mcp_oauth, "refresh_tokens", refresh)

        counts = await mcp_connection_service.sweep_oauth_connections(AsyncMock())

        assert counts == {"checked": 1, "refreshed": 0, "needs_authorization": 1, "skipped": 0}
        repo.get_by_id_for_update.assert_not_awaited()
        refresh.assert_not_awaited()
        assert self._written(repo)["last_status"] == "error"


class TestMcpConnectionService:
    @pytest.fixture
    def service(self):
        return McpConnectionService(db=AsyncMock())

    @pytest.fixture
    def repo(self, monkeypatch):
        mock_repo = MagicMock()
        mock_repo.get_by_id = AsyncMock()
        mock_repo.get_by_name = AsyncMock(return_value=None)
        mock_repo.list_for_user = AsyncMock(return_value=([], 0))
        mock_repo.create = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo.delete = AsyncMock()
        monkeypatch.setattr(mcp_connection_service, "mcp_connection_repo", mock_repo)
        return mock_repo

    @pytest.mark.anyio
    async def test_settings_lists_a_connection_the_user_switched_off(self, service, repo):
        """Only the chat turn wants the enabled ones. The Settings listing is
        where a disabled connection gets switched back on, so hiding it there
        would strand it."""
        conn = _connection(is_enabled=False)
        repo.list_for_user.return_value = ([conn], 1)

        items, total = await service.list_for_user(user_id=conn.user_id)

        assert (items, total) == ([conn], 1)
        assert repo.list_for_user.call_args.kwargs == {"user_id": conn.user_id}

    @pytest.mark.anyio
    async def test_create_blocks_internal_urls(self, service, repo):
        """As a refusal naming the field, not as the `ValueError` the guard
        raises - which no handler maps, so it left as a 500 (#861)."""
        data = McpConnectionCreate(name="internal", url="http://127.0.0.1:8000/mcp")
        with pytest.raises(BadRequestError) as excinfo:
            await service.create(user_id=uuid4(), data=data)
        assert excinfo.value.details == {
            "fields": [{"field": "url", "message": excinfo.value.message}]
        }
        assert excinfo.value.status_code == 400
        repo.create.assert_not_called()

    @pytest.mark.anyio
    async def test_create_seals_the_token_for_its_owner(self, service, repo, monkeypatch):
        _allow_any_url(monkeypatch)
        user_id = uuid4()
        data = McpConnectionCreate(
            name="github", url="https://example.com/mcp", auth_token="secret"
        )
        await service.create(user_id=user_id, data=data)

        stored = repo.create.call_args.kwargs["auth_token"]
        assert stored != "secret"
        assert unseal(stored, scope=VaultScope.user(user_id)) == "secret"
        # And nobody else's envelope opens it.
        with pytest.raises(BadRequestError, match="Failed to decrypt"):
            unseal(stored, scope=VaultScope.user(uuid4()))

    @pytest.mark.anyio
    async def test_create_without_token_stores_none(self, service, repo, monkeypatch):
        _allow_any_url(monkeypatch)
        data = McpConnectionCreate(name="github", url="https://example.com/mcp")
        await service.create(user_id=uuid4(), data=data)
        assert repo.create.call_args.kwargs["auth_token"] is None

    @pytest.mark.anyio
    async def test_create_refuses_a_name_this_user_already_has(self, service, repo, monkeypatch):
        """The name becomes the tool prefix inside the agent. Two connections
        sharing one means the second server's tools silently never appear."""
        _allow_any_url(monkeypatch)
        repo.get_by_name.return_value = _connection(name="github")

        with pytest.raises(AlreadyExistsError):
            await service.create(
                user_id=uuid4(),
                data=McpConnectionCreate(name="github", url="https://example.com/mcp"),
            )

        repo.create.assert_not_called()

    @pytest.mark.anyio
    async def test_create_losing_the_race_on_a_name_is_a_conflict_not_a_crash(
        self, service, repo, monkeypatch
    ):
        """Two requests can both pass the name check before either one inserts.
        `uq_mcp_connections_user_name` is what actually decides, and the loser
        must get the same 409 as if it had simply arrived second - not a 500."""
        _allow_any_url(monkeypatch)
        repo.create.side_effect = IntegrityError("INSERT", {}, Exception("duplicate key"))

        with pytest.raises(AlreadyExistsError) as refused:
            await service.create(
                user_id=uuid4(),
                data=McpConnectionCreate(name="github", url="https://example.com/mcp"),
            )

        assert refused.value.details == {"name": "github"}

    @pytest.mark.anyio
    async def test_renaming_onto_another_connections_name_is_refused(self, service, repo):
        """Same collision as at create, and the same consequence: one of the two
        servers stops being reachable from the agent."""
        user_id = uuid4()
        conn = _connection(user_id=user_id, name="github")
        repo.get_by_id.return_value = conn
        repo.get_by_name.return_value = _connection(user_id=user_id, name="linear")

        with pytest.raises(AlreadyExistsError):
            await service.update(
                user_id=user_id,
                connection_id=conn.id,
                data=McpConnectionUpdate(name="linear"),
            )

        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_a_change_that_touches_neither_url_nor_token_keeps_the_last_check_result(
        self, service, repo
    ):
        """The probe result describes a server and the credential used to reach
        it. Renaming a connection or switching it off changes neither, and
        blanking the result would show "never checked" for a working server."""
        user_id = uuid4()
        conn = _connection(user_id=user_id, name="github", last_status="ok")
        repo.get_by_id.return_value = conn

        await service.update(
            user_id=user_id,
            connection_id=conn.id,
            data=McpConnectionUpdate(name="linear", is_enabled=False),
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["name"] == "linear"
        assert "last_status" not in update_data
        assert "last_checked_at" not in update_data

    @pytest.mark.anyio
    async def test_clearing_the_allowlist_exposes_every_tool_again(self, service, repo):
        """`allowed_tools: null` in a PATCH body cannot be told apart from "not
        provided", so the reset needs its own flag. Without it a user could
        narrow an allowlist and never widen it back."""
        user_id = uuid4()
        conn = _connection(user_id=user_id, allowed_tools=["search_issues"])
        repo.get_by_id.return_value = conn

        await service.update(
            user_id=user_id,
            connection_id=conn.id,
            data=McpConnectionUpdate(clear_allowed_tools=True),
        )

        assert repo.update.call_args.kwargs["update_data"]["allowed_tools"] is None

    @pytest.mark.anyio
    async def test_an_update_that_asks_for_nothing_writes_nothing(self, service, repo):
        """An empty PATCH body must not bump `updated_at` - a row that changes
        for no reason is one that looks edited to whoever reads it next."""
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        repo.get_by_id.return_value = conn

        result = await service.update(
            user_id=user_id, connection_id=conn.id, data=McpConnectionUpdate()
        )

        assert result is conn
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_deleting_a_connection_removes_the_row_holding_the_credential(
        self, service, repo
    ):
        """Deleting is the only way a user revokes a token they pasted in, so it
        has to reach the row - and the row it reaches is the one ownership was
        checked against, never the id the request named."""
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        repo.get_by_id.return_value = conn

        await service.delete(user_id=user_id, connection_id=conn.id)

        assert repo.delete.call_args.kwargs["db_connection"] is conn

    @pytest.mark.anyio
    async def test_update_reseals_a_replacement_token_for_its_owner(self, service, repo):
        """A rotation has to record which master key sealed the new envelope.

        One version governs every secret in the row, so writing a new token
        without it would leave the row claiming a version its ciphertext was not
        sealed under.
        """
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        conn.auth_token = _seal_into(conn, "old")
        repo.get_by_id.return_value = conn

        await service.update(
            user_id=user_id,
            connection_id=conn.id,
            data=McpConnectionUpdate(auth_token="new-token"),
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["secret_key_version"] == 1
        assert unseal(update_data["auth_token"], scope=VaultScope.user(user_id)) == "new-token"

    @pytest.mark.anyio
    async def test_update_empty_token_clears_it(self, service, repo):
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        conn.auth_token = _seal_into(conn, "old")
        repo.get_by_id.return_value = conn

        await service.update(
            user_id=user_id,
            connection_id=conn.id,
            data=McpConnectionUpdate(auth_token=""),
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["auth_token"] is None
        # Credentials changed → stale check result is reset.
        assert update_data["last_status"] is None

    @pytest.mark.anyio
    async def test_update_url_revalidates_ssrf(self, service, repo):
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        repo.get_by_id.return_value = conn

        with pytest.raises(BadRequestError) as excinfo:
            await service.update(
                user_id=user_id,
                connection_id=conn.id,
                data=McpConnectionUpdate(url="http://169.254.169.254/mcp"),
            )

        assert excinfo.value.details == {
            "fields": [{"field": "url", "message": excinfo.value.message}]
        }
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_other_users_connection_is_not_found(self, service, repo):
        repo.get_by_id.return_value = _connection(user_id=uuid4())
        with pytest.raises(NotFoundError):
            await service.delete(user_id=uuid4(), connection_id=uuid4())

    @pytest.mark.anyio
    async def test_test_records_failure(self, service, repo, monkeypatch):
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        repo.get_by_id.return_value = conn
        repo.update.return_value = conn

        async def failing_probe(url, headers=None, timeout=None):
            raise TimeoutError

        monkeypatch.setattr(mcp_connection_service, "probe_mcp_server", failing_probe)

        _, tools, error = await service.test(user_id=user_id, connection_id=conn.id)

        assert tools == []
        assert error is not None and "timed out" in error
        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["last_status"] == "error"

    @pytest.mark.anyio
    async def test_test_records_success_and_returns_tools(self, service, repo, monkeypatch):
        user_id = uuid4()
        conn = _connection(user_id=user_id)
        repo.get_by_id.return_value = conn
        repo.update.return_value = conn

        async def ok_probe(url, headers=None, timeout=None):
            return [McpToolInfo(name="search", description="Search things")]

        monkeypatch.setattr(mcp_connection_service, "probe_mcp_server", ok_probe)

        _, tools, error = await service.test(user_id=user_id, connection_id=conn.id)

        assert error is None
        assert [t.name for t in tools] == ["search"]
        assert repo.update.call_args.kwargs["update_data"]["last_status"] == "ok"

    @pytest.mark.anyio
    async def test_test_on_an_unauthorized_connection_reports_that_and_does_not_dial_out(
        self, service, repo, monkeypatch
    ):
        """Probing with no credentials would tell the user their server is
        broken when what is missing is their consent - and would send an
        anonymous request to a third party to find that out."""
        user_id = uuid4()
        conn = _connection(user_id=user_id, auth_type="oauth", oauth_payload=None)
        repo.get_by_id.return_value = conn
        repo.update.return_value = conn

        async def never_probed(url, headers=None, timeout=None):
            raise AssertionError("an unauthorized connection must not be probed")

        monkeypatch.setattr(mcp_connection_service, "probe_mcp_server", never_probed)

        _, tools, error = await service.test(user_id=user_id, connection_id=conn.id)

        assert tools == []
        assert error is not None and "authorized" in error
        update_data = repo.update.call_args.kwargs["update_data"]
        assert (update_data["last_status"], update_data["last_error"]) == ("error", error)

    @pytest.mark.anyio
    async def test_oauth_start_will_not_take_over_a_token_based_connection(
        self, service, repo, monkeypatch
    ):
        """Names are unique per user, so an OAuth flow started under an existing
        bearer connection's name would have to overwrite it - discarding a token
        the user pasted in once and cannot read back out."""
        _allow_any_url(monkeypatch)
        repo.get_by_name.return_value = _connection(name="github", auth_type="bearer")
        discovered = mcp_oauth.DiscoveredServer(
            authorization_endpoint="https://srv/authorize",
            token_endpoint="https://srv/token",
            registration_endpoint=None,
            resource="https://srv/mcp",
            scope=None,
            metadata=MagicMock(),
        )
        monkeypatch.setattr(mcp_oauth, "discover", AsyncMock(return_value=discovered))
        monkeypatch.setattr(mcp_oauth, "register_client", AsyncMock(return_value=("cid", None)))

        with pytest.raises(AlreadyExistsError):
            await service.oauth_start(user_id=uuid4(), name="github", url="https://srv/mcp")

        repo.update.assert_not_called()
        repo.create.assert_not_called()

    @pytest.mark.anyio
    async def test_oauth_start_registers_and_persists_pending(self, service, repo, monkeypatch):
        _allow_any_url(monkeypatch)
        discovered = mcp_oauth.DiscoveredServer(
            authorization_endpoint="https://srv/authorize",
            token_endpoint="https://srv/token",
            registration_endpoint="https://srv/register",
            resource="https://srv/mcp",
            scope="read write",
            metadata=MagicMock(),
        )
        monkeypatch.setattr(mcp_oauth, "discover", AsyncMock(return_value=discovered))
        monkeypatch.setattr(mcp_oauth, "register_client", AsyncMock(return_value=("cid", "csec")))

        user_id = uuid4()
        url = await service.oauth_start(user_id=user_id, name="linear", url="https://srv/mcp")

        assert url.startswith("https://srv/authorize?")
        assert "code_challenge=" in url and "state=" in url
        kwargs = repo.create.call_args.kwargs
        assert kwargs["auth_type"] == "oauth"
        assert kwargs["oauth_state"] and kwargs["oauth_pending_payload"]
        # Nothing lands in the live payload until the callback succeeds.
        assert kwargs.get("oauth_payload") is None
        # The persisted payload holds the PKCE verifier but no tokens yet.
        payload = McpOAuthPayload.model_validate_json(
            unseal(kwargs["oauth_pending_payload"], scope=VaultScope.user(user_id))
        )
        assert payload.code_verifier and payload.access_token is None
        assert payload.client_id == "cid"
        # Stamped so the callback can refuse a flow the user never finished.
        assert datetime.now(UTC).timestamp() - payload.started_at < mcp_oauth.FLOW_TTL_SECS

    @pytest.mark.anyio
    async def test_oauth_start_keeps_working_tokens_until_consent(self, service, repo, monkeypatch):
        """Re-authorizing must not break the connection if the user closes the
        consent tab - the live tokens (and the URL) stay put until it lands."""
        _allow_any_url(monkeypatch)
        live = _oauth_connection(
            _base_payload(access_token="live-token"), name="linear", url="https://srv/mcp"
        )
        repo.get_by_name.return_value = live
        discovered = mcp_oauth.DiscoveredServer(
            authorization_endpoint="https://srv/authorize",
            token_endpoint="https://srv/token",
            registration_endpoint=None,
            resource="https://other/mcp",
            scope=None,
            metadata=MagicMock(),
        )
        monkeypatch.setattr(mcp_oauth, "discover", AsyncMock(return_value=discovered))
        monkeypatch.setattr(mcp_oauth, "register_client", AsyncMock(return_value=("cid", None)))

        await service.oauth_start(user_id=uuid4(), name="linear", url="https://other/mcp")

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["oauth_pending_payload"]
        assert "oauth_payload" not in update_data  # the working tokens survive
        assert "url" not in update_data  # and so does the URL they belong to

    @pytest.mark.anyio
    async def test_oauth_start_rejects_internal_urls(self, service, repo):
        with pytest.raises(BadRequestError) as excinfo:
            await service.oauth_start(
                user_id=uuid4(), name="evil", url="http://169.254.169.254/mcp"
            )
        assert excinfo.value.details == {
            "fields": [{"field": "url", "message": excinfo.value.message}]
        }
        repo.create.assert_not_called()

    @pytest.mark.anyio
    async def test_oauth_callback_exchanges_and_clears_state(self, service, repo, monkeypatch):
        pending = _connection(auth_type="oauth", url="https://srv/mcp", oauth_state="state-xyz")
        pending.oauth_pending_payload = _seal_into(
            pending,
            _base_payload(
                code_verifier="verifier", server_url="https://moved/mcp"
            ).model_dump_json(),
        )
        repo.get_by_oauth_state = AsyncMock(return_value=pending)
        repo.update.return_value = pending
        token = OAuthToken(access_token="AT", refresh_token="RT", expires_in=3600)
        monkeypatch.setattr(mcp_oauth, "exchange_code", AsyncMock(return_value=token))

        await service.oauth_callback(state="state-xyz", code="the-code")

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["oauth_state"] is None  # no longer pending
        assert update_data["oauth_pending_payload"] is None
        assert update_data["last_status"] == "ok"
        # The URL the tokens were issued for is applied together with them.
        assert update_data["url"] == "https://moved/mcp"
        payload = McpOAuthPayload.model_validate_json(
            _open_from(pending, update_data["oauth_payload"])
        )
        assert payload.access_token == "AT" and payload.refresh_token == "RT"
        assert payload.code_verifier is None

    @pytest.mark.anyio
    async def test_oauth_callback_unknown_state_is_not_found(self, service, repo):
        repo.get_by_oauth_state = AsyncMock(return_value=None)
        with pytest.raises(NotFoundError):
            await service.oauth_callback(state="nope", code="x")

    @pytest.mark.anyio
    async def test_oauth_callback_rejects_an_expired_flow(self, service, repo, monkeypatch):
        """The state token is the only thing authenticating this endpoint, and
        it travels through the provider and the browser's history - a consent
        redirect the user never finished must stop being redeemable."""
        started = datetime.now(UTC).timestamp() - mcp_oauth.FLOW_TTL_SECS - 1
        stale = _connection(auth_type="oauth", oauth_state="state-old")
        stale.oauth_pending_payload = _seal_into(
            stale,
            _base_payload(code_verifier="verifier", started_at=started).model_dump_json(),
        )
        repo.get_by_oauth_state = AsyncMock(return_value=stale)
        exchange_mock = AsyncMock()
        monkeypatch.setattr(mcp_oauth, "exchange_code", exchange_mock)

        with pytest.raises(mcp_oauth.OAuthError, match="expired"):
            await service.oauth_callback(state="state-old", code="the-code")

        exchange_mock.assert_not_awaited()
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_oauth_callback_on_unreadable_payload_asks_to_start_again(self, service, repo):
        """A rotated SECRET_KEY makes the pending payload undecryptable. That's
        a dead flow the user restarts, not a 500."""
        stale = _connection(
            auth_type="oauth",
            oauth_state="state-broken",
            oauth_pending_payload="enc:not-valid-ciphertext",
        )
        repo.get_by_oauth_state = AsyncMock(return_value=stale)

        with pytest.raises(mcp_oauth.OAuthError, match="no longer valid"):
            await service.oauth_callback(state="state-broken", code="the-code")

    @pytest.mark.anyio
    async def test_update_url_drops_oauth_tokens(self, service, repo, monkeypatch):
        """Tokens are bound to the host they were issued for - moving the URL
        must not send a provider's access token to a different server."""
        _allow_any_url(monkeypatch)
        user_id = uuid4()
        conn = _oauth_connection(
            _base_payload(access_token="AT"), user_id=user_id, oauth_state=None
        )
        repo.get_by_id.return_value = conn

        await service.update(
            user_id=user_id,
            connection_id=conn.id,
            data=McpConnectionUpdate(url="https://elsewhere.example/mcp"),
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["oauth_payload"] is None
        assert update_data["oauth_pending_payload"] is None
        assert update_data["oauth_state"] is None


class TestOrganizationConnections:
    """The servers an agent can be built on, and the credential they carry.

    Everything here turns on two things a personal connection does not have: a
    credential sealed for the organization rather than for the deployment, and
    no owner at all - which is what keeps the personal routes, that authorize on
    `user_id` alone, from ever reaching one of these rows.
    """

    @pytest.fixture
    def ctx(self) -> AuthContext:
        return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)

    @pytest.fixture
    def service(self):
        return McpConnectionService(db=AsyncMock())

    @pytest.fixture
    def repo(self, monkeypatch):
        mock_repo = MagicMock()
        mock_repo.list_org_scoped = AsyncMock(return_value=([], 0))
        mock_repo.get_org_scoped_by_id = AsyncMock(return_value=None)
        mock_repo.get_org_scoped_by_name = AsyncMock(return_value=None)
        mock_repo.get_by_id = AsyncMock()
        mock_repo.create_org_scoped = AsyncMock()
        mock_repo.update = AsyncMock()
        mock_repo.delete = AsyncMock()
        monkeypatch.setattr(mcp_connection_service, "mcp_connection_repo", mock_repo)
        return mock_repo

    @pytest.fixture
    def audit(self, monkeypatch):
        recorder = AsyncMock()
        monkeypatch.setattr(mcp_connection_service, "record_audit", recorder)
        return recorder

    def _org_connection(self, ctx: AuthContext, **overrides) -> McpConnection:
        return _connection(
            scope="org",
            user_id=None,
            created_by_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            **overrides,
        )

    # -- listing --------------------------------------------------------

    @pytest.mark.anyio
    async def test_listing_asks_only_for_this_organizations_servers(self, service, ctx, repo):
        conn = self._org_connection(ctx)
        repo.list_org_scoped.return_value = ([conn], 1)

        items, total = await service.list_for_org(ctx)

        assert (items, total) == ([conn], 1)
        assert repo.list_org_scoped.call_args.kwargs == {"organization_id": ctx.organization_id}

    # -- creating -------------------------------------------------------

    @pytest.mark.anyio
    async def test_the_credential_is_sealed_for_this_organization(
        self, service, ctx, repo, audit, monkeypatch
    ):
        """Not the deployment key. A shared credential sealed globally would
        survive being lifted into another tenant's row, which is the one thing
        the vault exists to prevent."""
        _allow_any_url(monkeypatch)

        await service.create_for_org(
            ctx,
            OrgMcpConnectionCreate(
                name="github", url="https://example.com/mcp", auth_token="ghp-secret-9876"
            ),
        )

        stored = repo.create_org_scoped.call_args.kwargs
        assert stored["sealed_token"] != "ghp-secret-9876"
        assert "ghp-secret-9876" not in stored["sealed_token"]
        assert (
            unseal(
                stored["sealed_token"],
                scope=VaultScope.organization(ctx.organization_id),
                key_version=stored["secret_key_version"],
            )
            == "ghp-secret-9876"
        )

    @pytest.mark.anyio
    async def test_a_server_needing_no_credential_stores_none(
        self, service, ctx, repo, audit, monkeypatch
    ):
        """An empty secret is refused by the vault, so a tokenless server has to
        skip sealing rather than seal `""` and fail at the provider later."""
        _allow_any_url(monkeypatch)

        await service.create_for_org(
            ctx, OrgMcpConnectionCreate(name="docs", url="https://example.com/mcp")
        )

        stored = repo.create_org_scoped.call_args.kwargs
        assert (stored["sealed_token"], stored["secret_key_version"]) == (None, 1)

    @pytest.mark.anyio
    async def test_the_row_records_who_added_it_and_belongs_to_nobody(
        self, service, ctx, repo, audit, monkeypatch
    ):
        _allow_any_url(monkeypatch)

        await service.create_for_org(
            ctx,
            OrgMcpConnectionCreate(
                name="linear", url="https://example.com/mcp", catalog_key="linear"
            ),
        )

        stored = repo.create_org_scoped.call_args.kwargs
        assert stored["organization_id"] == ctx.organization_id
        assert stored["created_by_user_id"] == ctx.user_id
        assert stored["catalog_key"] == "linear"

    @pytest.mark.anyio
    async def test_an_unknown_catalog_key_is_refused_before_anything_is_written(
        self, service, ctx, repo, audit
    ):
        """A key nothing recognises renders in the Builder as a server with no
        name and no logo, which reads as a broken row rather than as a typo."""
        with pytest.raises(BadRequestError, match="Unknown catalog server"):
            await service.create_for_org(
                ctx,
                OrgMcpConnectionCreate(
                    name="github", url="https://example.com/mcp", catalog_key="githbu"
                ),
            )
        repo.create_org_scoped.assert_not_called()

    @pytest.mark.anyio
    async def test_creating_blocks_internal_urls(self, service, ctx, repo, audit):
        with pytest.raises(BadRequestError) as excinfo:
            await service.create_for_org(
                ctx, OrgMcpConnectionCreate(name="internal", url="http://127.0.0.1:8000/mcp")
            )
        assert excinfo.value.details == {
            "fields": [{"field": "url", "message": excinfo.value.message}]
        }
        repo.create_org_scoped.assert_not_called()

    @pytest.mark.anyio
    async def test_a_name_already_taken_in_this_organization_is_refused(
        self, service, ctx, repo, audit, monkeypatch
    ):
        """The name becomes the agent's tool prefix, so two servers sharing one
        are two sets of tools nobody can tell apart in a spec."""
        _allow_any_url(monkeypatch)
        repo.get_org_scoped_by_name.return_value = self._org_connection(ctx)

        with pytest.raises(AlreadyExistsError):
            await service.create_for_org(
                ctx, OrgMcpConnectionCreate(name="github", url="https://example.com/mcp")
            )
        repo.create_org_scoped.assert_not_called()

    @pytest.mark.anyio
    async def test_a_name_that_collided_in_the_database_is_reported_as_a_collision(
        self, service, ctx, repo, audit, monkeypatch
    ):
        """Two admins adding the same server at once both pass the lookup; the
        partial unique index catches the loser, who deserves the same message
        as the one who lost the race by a second."""
        _allow_any_url(monkeypatch)
        repo.create_org_scoped.side_effect = IntegrityError("insert", {}, Exception("dup"))

        with pytest.raises(AlreadyExistsError):
            await service.create_for_org(
                ctx, OrgMcpConnectionCreate(name="github", url="https://example.com/mcp")
            )

    @pytest.mark.anyio
    async def test_the_audit_entry_names_the_server_and_never_the_token(
        self, service, ctx, repo, audit, monkeypatch
    ):
        _allow_any_url(monkeypatch)
        repo.create_org_scoped.return_value = self._org_connection(ctx)

        await service.create_for_org(
            ctx,
            OrgMcpConnectionCreate(
                name="github", url="https://example.com/mcp", auth_token="ghp-secret-9876"
            ),
        )

        recorded = audit.call_args.kwargs
        assert recorded["action"] == "mcp_connection.created"
        assert recorded["organization_id"] == ctx.organization_id
        assert recorded["details"] == {
            "name": "github",
            "url": "https://example.com/mcp",
            "catalog_key": None,
        }
        assert "ghp-secret-9876" not in str(recorded)

    # -- updating -------------------------------------------------------

    @pytest.mark.anyio
    async def test_a_replacement_credential_is_resealed_for_this_organization(
        self, service, ctx, repo, monkeypatch
    ):
        _allow_any_url(monkeypatch)
        conn = self._org_connection(ctx)
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(auth_token="ghp-rotated-4321")
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert "ghp-rotated-4321" not in update_data["auth_token"]
        assert (
            unseal(
                update_data["auth_token"],
                scope=VaultScope.organization(ctx.organization_id),
                key_version=update_data["secret_key_version"],
            )
            == "ghp-rotated-4321"
        )

    @pytest.mark.anyio
    async def test_an_empty_credential_clears_the_stored_one(self, service, ctx, repo):
        conn = self._org_connection(ctx, auth_token="envelope")
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(auth_token="")
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["auth_token"] is None
        # No new envelope, so the version that sealed the old one is left alone
        # rather than rewritten to describe a token that no longer exists.
        assert "secret_key_version" not in update_data

    @pytest.mark.anyio
    async def test_moving_the_url_somewhere_internal_is_refused_by_field(self, service, ctx, repo):
        """The other half of #861: a connection may not be *edited* into the
        deployment's own network either, and that refusal is a 400 too."""
        conn = self._org_connection(ctx)
        repo.get_org_scoped_by_id.return_value = conn

        with pytest.raises(BadRequestError) as excinfo:
            await service.update_for_org(
                ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(url="http://[::1]/mcp")
            )

        assert excinfo.value.details == {
            "fields": [{"field": "url", "message": excinfo.value.message}]
        }
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_moving_the_url_discards_the_previous_check_result(
        self, service, ctx, repo, monkeypatch
    ):
        """A green tick next to a server nobody has reached since it moved is
        worse than no tick: it is the reason somebody publishes a broken agent."""
        _allow_any_url(monkeypatch)
        conn = self._org_connection(ctx, last_status="ok", last_error=None)
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx,
            connection_id=conn.id,
            data=OrgMcpConnectionUpdate(url="https://elsewhere.example/mcp"),
        )

        update_data = repo.update.call_args.kwargs["update_data"]
        assert update_data["last_status"] is None
        assert update_data["last_checked_at"] is None

    @pytest.mark.anyio
    async def test_renaming_onto_another_servers_name_is_refused(self, service, ctx, repo):
        conn = self._org_connection(ctx, name="github")
        repo.get_org_scoped_by_id.return_value = conn
        repo.get_org_scoped_by_name.return_value = self._org_connection(ctx, name="linear")

        with pytest.raises(AlreadyExistsError):
            await service.update_for_org(
                ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(name="linear")
            )
        repo.update.assert_not_called()

    @pytest.mark.anyio
    async def test_renaming_onto_a_free_name_goes_through(self, service, ctx, repo):
        conn = self._org_connection(ctx, name="github")
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(name="linear")
        )

        assert repo.update.call_args.kwargs["update_data"] == {"name": "linear"}

    @pytest.mark.anyio
    async def test_renaming_a_server_to_the_name_it_already_has_is_not_a_collision(
        self, service, ctx, repo
    ):
        conn = self._org_connection(ctx, name="github")
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(name="github")
        )

        repo.get_org_scoped_by_name.assert_not_called()
        assert repo.update.call_args.kwargs["update_data"] == {"name": "github"}

    @pytest.mark.anyio
    async def test_clearing_the_allowlist_exposes_every_tool_again(self, service, ctx, repo):
        conn = self._org_connection(ctx, allowed_tools=["search"])
        repo.get_org_scoped_by_id.return_value = conn

        await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate(clear_allowed_tools=True)
        )

        assert repo.update.call_args.kwargs["update_data"]["allowed_tools"] is None

    @pytest.mark.anyio
    async def test_an_update_that_asks_for_nothing_writes_nothing(self, service, ctx, repo):
        conn = self._org_connection(ctx)
        repo.get_org_scoped_by_id.return_value = conn

        result = await service.update_for_org(
            ctx, connection_id=conn.id, data=OrgMcpConnectionUpdate()
        )

        assert result is conn
        repo.update.assert_not_called()

    # -- authorizing ----------------------------------------------------

    @pytest.mark.anyio
    async def test_authorizing_a_shared_server_stages_the_flow_on_the_organizations_row(
        self, service, ctx, repo, monkeypatch
    ):
        """The consent is one person's; the connection is not. A pending flow
        sealed with that member's envelope would leave a row the organization
        owns and only its author could ever open - and a name checked in their
        personal namespace would miss the collision that matters here."""
        _allow_any_url(monkeypatch)
        discovered = mcp_oauth.DiscoveredServer(
            authorization_endpoint="https://srv/authorize",
            token_endpoint="https://srv/token",
            registration_endpoint=None,
            resource="https://srv/mcp",
            scope=None,
            metadata=MagicMock(),
        )
        monkeypatch.setattr(mcp_oauth, "discover", AsyncMock(return_value=discovered))
        monkeypatch.setattr(mcp_oauth, "register_client", AsyncMock(return_value=("cid", None)))

        url = await service.oauth_start_for_org(ctx, name="linear", url="https://srv/mcp")

        assert url.startswith("https://srv/authorize?")
        assert repo.get_org_scoped_by_name.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "name": "linear",
        }
        stored = repo.create_org_scoped.await_args.kwargs
        assert stored["organization_id"] == ctx.organization_id
        assert stored["created_by_user_id"] == ctx.subject_id
        assert (stored["auth_type"], stored["sealed_token"]) == ("oauth", None)
        payload = McpOAuthPayload.model_validate_json(
            unseal(
                stored["oauth_pending_payload"],
                scope=VaultScope.organization(ctx.organization_id),
            )
        )
        # Staged only: the verifier the callback needs, and no tokens yet.
        assert payload.code_verifier and payload.access_token is None

    # -- deleting and probing -------------------------------------------

    @pytest.mark.anyio
    async def test_deleting_removes_the_row_and_leaves_a_trail(self, service, ctx, repo, audit):
        conn = self._org_connection(ctx, name="github")
        repo.get_org_scoped_by_id.return_value = conn

        await service.delete_for_org(ctx, connection_id=conn.id)

        assert repo.delete.call_args.kwargs == {"db_connection": conn}
        recorded = audit.call_args.kwargs
        assert recorded["action"] == "mcp_connection.deleted"
        assert recorded["details"] == {"name": "github"}

    @pytest.mark.anyio
    async def test_a_probe_records_what_it_found(self, service, ctx, repo, monkeypatch):
        conn = self._org_connection(ctx)
        repo.get_org_scoped_by_id.return_value = conn
        tools = [McpToolInfo(name="search", description="Search")]
        monkeypatch.setattr(
            mcp_connection_service, "probe_mcp_server", AsyncMock(return_value=tools)
        )

        _connection_out, found, error = await service.test_for_org(ctx, connection_id=conn.id)

        assert (found, error) == (tools, None)
        assert repo.update.call_args.kwargs["update_data"]["last_status"] == "ok"

    # -- the tenant boundary --------------------------------------------

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda service, ctx, connection_id: service.update_for_org(
                    ctx, connection_id=connection_id, data=OrgMcpConnectionUpdate(name="taken")
                ),
                id="update",
            ),
            pytest.param(
                lambda service, ctx, connection_id: service.delete_for_org(
                    ctx, connection_id=connection_id
                ),
                id="delete",
            ),
            pytest.param(
                lambda service, ctx, connection_id: service.test_for_org(
                    ctx, connection_id=connection_id
                ),
                id="test",
            ),
        ],
    )
    async def test_a_server_this_organization_does_not_own_is_not_found(
        self, service, ctx, repo, audit, call
    ):
        """Every write goes through the same scoped lookup, and a refusal reads
        as "not found" so an id cannot be used to probe what another tenant has."""
        connection_id = uuid4()

        with pytest.raises(NotFoundError):
            await call(service, ctx, connection_id)

        assert repo.get_org_scoped_by_id.call_args.kwargs == {
            "connection_id": connection_id,
            "organization_id": ctx.organization_id,
        }

    @pytest.mark.anyio
    async def test_the_personal_routes_cannot_reach_an_organization_server(self, service, repo):
        """`/me/mcp-connections` authorizes on `user_id` and asks for no
        organization permission. Without the scope check, whoever created a
        shared server could repoint a published agent at a host of their own."""
        user_id = uuid4()
        conn = _connection(scope="org", user_id=user_id, organization_id=uuid4())
        repo.get_by_id.return_value = conn

        with pytest.raises(NotFoundError):
            await service.delete(user_id=user_id, connection_id=conn.id)
        repo.delete.assert_not_called()


class TestOrgReadSchema:
    def test_the_sealed_credential_never_leaves_the_backend(self):
        """A response says a credential exists, never what it is - the same
        contract as a provider key, and the reason there is no read endpoint."""
        organization_id = uuid4()
        sealed = seal("ghp-secret-9876", scope=VaultScope.organization(organization_id))
        conn = _connection(
            scope="org",
            user_id=None,
            organization_id=organization_id,
            catalog_key="github",
            auth_token=sealed.ciphertext,
            secret_key_version=sealed.key_version,
        )

        read = OrgMcpConnectionRead.from_model(conn)

        assert (read.has_auth_token, read.catalog_key) == (True, "github")
        rendered = read.model_dump_json()
        assert "ghp-secret-9876" not in rendered
        assert sealed.ciphertext not in rendered


class TestOAuthRequestSafety:
    """Discovery lets the remote server choose most of the URLs we call, so
    every hop - redirects included - is checked and then dialled at the address
    that passed (#860).

    IP literals are used except where a hostname is the point: the validator
    short-circuits on a literal, so those tests never touch DNS.
    """

    @staticmethod
    def _client(handler) -> PinnedAsyncClient:
        return mcp_oauth._client(httpx.MockTransport(handler))

    @staticmethod
    def _resolves(monkeypatch, *rounds: str) -> list[str]:
        """One DNS answer per call, the last one repeating; records the names."""
        asked: list[str] = []
        remaining = iter(rounds)

        def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple]:
            asked.append(host)
            return [(2, 1, 6, "", (next(remaining, rounds[-1]), port))]

        monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
        return asked

    @pytest.mark.anyio
    async def test_a_discovery_document_naming_a_private_address_is_refused(self, monkeypatch):
        """The authorization server comes out of the server's own metadata, so
        this is the first hop an attacker controls outright."""
        self._resolves(monkeypatch, "169.254.169.254")
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={})

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://auth.attacker.test/.well-known/oauth")
            with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
                await mcp_oauth._send(client, request)

        assert seen == []

    @pytest.mark.anyio
    async def test_a_refused_hop_is_reported_without_the_url_it_refused(self, monkeypatch):
        """The refusal crosses `httpx` out of the transport and reaches a
        browser as a toast, so what it may say is the same question #861
        answered for the connection dialog. The endpoint this flow POSTs to is
        reached with credentials, and its query string is the server's to
        write."""
        self._resolves(monkeypatch, "10.0.0.9")

        async with self._client(lambda request: httpx.Response(200, json={})) as client:
            request = client.build_request(
                "POST", "https://auth.attacker.test/token?client_secret=sh-secret-value"
            )
            with pytest.raises(mcp_oauth.OAuthError) as excinfo:
                await mcp_oauth._send(client, request)

        shown = str(excinfo.value)
        assert "sh-secret-value" not in shown
        assert "auth.attacker.test" not in shown
        assert "10.0.0.9" not in shown

    @pytest.mark.anyio
    async def test_a_name_that_turns_private_is_dialled_at_the_address_that_passed(
        self, monkeypatch
    ):
        """The rebinding case: public to the check, the metadata service to
        whatever resolves next. There is no next - the request goes to the
        address the check approved, naming the host only in `Host` and SNI."""
        asked = self._resolves(monkeypatch, "93.184.216.34", "169.254.169.254")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        async with self._client(handler) as client:
            request = client.build_request("POST", "https://token.attacker.test/token")
            response = await mcp_oauth._send(client, request)

        assert response.status_code == 200
        assert asked == ["token.attacker.test"]
        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["Host"] == "token.attacker.test"

    @pytest.mark.anyio
    async def test_redirect_to_internal_host_is_blocked(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
            )

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://93.184.216.34/.well-known/x")
            with pytest.raises(mcp_oauth.OAuthError):
                await mcp_oauth._send(client, request)

        # The first hop was allowed; the metadata address was never requested.
        assert seen == ["https://93.184.216.34/.well-known/x"]

    @pytest.mark.anyio
    async def test_a_redirect_to_a_new_host_is_re_checked_not_trusted(self, monkeypatch):
        """A second hop gets its own resolution, and its own refusal."""
        asked = self._resolves(monkeypatch, "93.184.216.34", "10.0.0.7")
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://intranet.attacker.test/x"})

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://auth.attacker.test/start")
            with pytest.raises(mcp_oauth.OAuthError, match="blocked address"):
                await mcp_oauth._send(client, request)

        assert asked == ["auth.attacker.test", "intranet.attacker.test"]
        assert len(seen) == 1

    @pytest.mark.anyio
    async def test_a_relative_redirect_follows_the_host_not_the_pinned_address(self, monkeypatch):
        """`next_request` is built from the URL we asked for. Were it built from
        the dialled one, `/moved` would resolve against the IP and the hop after
        it would be checked - and cached, and TLS-verified - as a bare address."""
        self._resolves(monkeypatch, "93.184.216.34")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": "/moved"})
            return httpx.Response(200, text="ok")

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://auth.example.test/start")
            response = await mcp_oauth._send(client, request)

        assert response.status_code == 200
        assert [r.headers["Host"] for r in seen] == ["auth.example.test"] * 2
        assert [r.url.host for r in seen] == ["93.184.216.34"] * 2

    @pytest.mark.anyio
    async def test_redirect_to_public_host_is_followed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "93.184.216.34":
                return httpx.Response(302, headers={"Location": "https://93.184.216.35/moved"})
            return httpx.Response(200, text="ok")

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://93.184.216.34/start")
            response = await mcp_oauth._send(client, request)

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_redirect_loop_gives_up(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://93.184.216.34/loop"})

        async with self._client(handler) as client:
            request = client.build_request("GET", "https://93.184.216.34/loop")
            with pytest.raises(mcp_oauth.OAuthError, match="redirects"):
                await mcp_oauth._send(client, request)

    @pytest.mark.anyio
    async def test_token_endpoint_body_is_not_surfaced(self, monkeypatch):
        """The OAuth error text reaches the user's browser - an internal
        service's reply must not ride along with it."""

        async def fake_send(client, request):
            return httpx.Response(
                500, text="redis: NOAUTH Authentication required", request=request
            )

        monkeypatch.setattr(mcp_oauth, "_send", fake_send)
        with pytest.raises(mcp_oauth.OAuthError) as exc_info:
            await mcp_oauth._token_request("https://93.184.216.34/token", {"grant_type": "x"})

        assert "redis" not in str(exc_info.value)
        assert "500" in str(exc_info.value)


class TestOAuthRefusalsDoNotQuoteTheServer:
    """An OAuth refusal reaches the browser - as a toast since #657 - so what it
    may say is written here rather than by whatever raised.

    `httpx` puts the failing request in its message, and the two requests this
    flow makes are a token grant and a client registration: a URL in that
    message is an endpoint reached with credentials. The vendor's text is not
    deleted, it moves to the log beside the raise (#686).
    """

    _LEAKY_URL = "https://auth.example.com/token?client_secret=shh-9f2c"

    @staticmethod
    def _discovered() -> mcp_oauth.DiscoveredServer:
        metadata = OAuthMetadata(
            issuer=AnyUrl("https://auth.example.com"),
            authorization_endpoint=AnyUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyUrl("https://auth.example.com/token"),
            registration_endpoint=AnyUrl("https://auth.example.com/register"),
            response_types_supported=["code"],
        )
        return mcp_oauth.DiscoveredServer(
            authorization_endpoint=str(metadata.authorization_endpoint),
            token_endpoint=str(metadata.token_endpoint),
            registration_endpoint=str(metadata.registration_endpoint),
            resource="https://mcp.example.com/",
            scope=None,
            metadata=metadata,
        )

    @pytest.mark.anyio
    async def test_an_unreachable_token_endpoint_is_named_by_its_class(self, monkeypatch, caplog):
        vendor_text = f"[Errno 61] Connection refused for {self._LEAKY_URL}"

        async def fake_send(client, request):
            raise httpx.ConnectError(vendor_text)

        monkeypatch.setattr(mcp_oauth, "_send", fake_send)
        with (
            caplog.at_level(logging.ERROR, logger="app.agents.mcp_oauth"),
            pytest.raises(mcp_oauth.OAuthError) as exc_info,
        ):
            await mcp_oauth._token_request(
                "https://auth.example.com/token", {"grant_type": "refresh_token"}
            )

        shown = str(exc_info.value)
        assert "client_secret" not in shown
        assert self._LEAKY_URL not in shown
        assert "ConnectError" in shown
        assert vendor_text in caplog.text

    @pytest.mark.anyio
    async def test_a_failed_registration_is_named_by_its_class(self, monkeypatch, caplog):
        vendor_text = f"Server disconnected without sending a response: {self._LEAKY_URL}"

        async def fake_send(client, request):
            raise httpx.ReadError(vendor_text)

        monkeypatch.setattr(mcp_oauth, "_send", fake_send)
        with (
            caplog.at_level(logging.ERROR, logger="app.agents.mcp_oauth"),
            pytest.raises(mcp_oauth.OAuthError) as exc_info,
        ):
            await mcp_oauth.register_client(
                self._discovered(), "https://app.example.com/oauth/callback"
            )

        shown = str(exc_info.value)
        assert "client_secret" not in shown
        assert self._LEAKY_URL not in shown
        assert "ReadError" in shown
        assert vendor_text in caplog.text

    @pytest.mark.anyio
    async def test_an_unreadable_token_response_does_not_echo_its_input(self, monkeypatch, caplog):
        """A pydantic `ValidationError` echoes the input it rejected, and here
        that input is the token payload - so a server that names the field
        wrongly used to have its own tokens read back to the browser."""

        async def fake_send(client, request):
            return httpx.Response(200, json={"token": "at-secret-9f2c"}, request=request)

        monkeypatch.setattr(mcp_oauth, "_send", fake_send)
        with (
            caplog.at_level(logging.ERROR, logger="app.agents.mcp_oauth"),
            pytest.raises(mcp_oauth.OAuthError) as exc_info,
        ):
            await mcp_oauth._token_request(
                "https://auth.example.com/token", {"grant_type": "authorization_code"}
            )

        shown = str(exc_info.value)
        assert "at-secret-9f2c" not in shown
        assert "ValidationError" in shown
        assert "at-secret-9f2c" in caplog.text


class TestAUrlNoRequestCanBeBuiltFor:
    """A discovery document may name a URL `httpx` will not parse at all, and
    that is the third-party server being malformed rather than this platform
    being broken - so it answers the 400 every other bad document answers.

    `httpx.InvalidURL` derives from `Exception` rather than from
    `httpx.HTTPError`, so it escaped all three of this module's catches and
    reached the unhandled-exception handler as a 500 with an empty body (#889).
    Neither `app.core.sanitize` nor `PinnedAsyncClient` could have stopped it:
    both need a request, and this is the failure to build one.

    Two shapes reach here, and both are the remote server's text. A bad port
    survives `urlparse` and is quoted back by `InvalidURL` - `Invalid port:
    'client_secret=…'` - which is what decides the wording. An endpoint over
    64 KiB survives `AnyHttpUrl` too, so it is the shape that reaches a stored
    `token_endpoint` and a `registration_endpoint` after discovery has already
    accepted the document.
    """

    _SERVER = "https://93.184.216.34/mcp"
    _BAD_PORT = (
        "https://auth.example.com:client_secret=sh-9f2c/.well-known/oauth-protected-resource"
    )
    _TOO_LONG = "https://93.184.216.35/token?p=" + "p" * 70_000

    @staticmethod
    def _serving(monkeypatch, handler) -> None:
        """Point every client `discover` opens at *handler* instead of a network."""
        real = mcp_oauth._client
        monkeypatch.setattr(mcp_oauth, "_client", lambda: real(httpx.MockTransport(handler)))

    @classmethod
    def _hinting_at_the_bad_port(cls, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                401,
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{cls._BAD_PORT}"'},
                json={},
            )
        return httpx.Response(404, json={})

    @staticmethod
    def _metadata(token_endpoint: str) -> dict[str, object]:
        return {
            "issuer": "https://93.184.216.35",
            "authorization_endpoint": "https://93.184.216.35/authorize",
            "token_endpoint": token_endpoint,
            "response_types_supported": ["code"],
        }

    @pytest.mark.anyio
    async def test_a_www_authenticate_hint_with_an_unusable_port_does_not_crash_discovery(
        self, monkeypatch
    ):
        """The header is remote-controlled text that reaches `httpx.Request`
        before anything here sees it. It used to raise `InvalidURL` out of
        `discover`; now the candidate is skipped and the flow gives the answer
        it gives for a server with no metadata."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return self._hinting_at_the_bad_port(request)

        self._serving(monkeypatch, handler)
        with pytest.raises(mcp_oauth.OAuthError) as exc_info:
            await mcp_oauth.discover(self._SERVER)

        assert "did not advertise OAuth metadata" in str(exc_info.value)
        assert "sh-9f2c" not in str(exc_info.value)
        # The hint was never requested; the well-known URIs after it still were.
        assert seen == [
            self._SERVER,
            "https://93.184.216.34/.well-known/oauth-protected-resource/mcp",
            "https://93.184.216.34/.well-known/oauth-protected-resource",
            "https://93.184.216.34/.well-known/oauth-authorization-server",
        ]

    @pytest.mark.anyio
    async def test_an_unusable_hint_ends_that_candidate_and_not_the_flow(self, monkeypatch):
        """The hint is the first of three candidates and the other two are
        derived from the URL an operator typed, so a server that writes its
        `WWW-Authenticate` header badly and its well-known documents correctly
        still connects."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/.well-known/oauth-protected-resource":
                return httpx.Response(
                    200,
                    json={
                        "resource": "https://93.184.216.34/mcp",
                        "authorization_servers": ["https://93.184.216.35"],
                    },
                )
            if request.url.path == "/.well-known/oauth-authorization-server":
                return httpx.Response(200, json=self._metadata("https://93.184.216.35/token"))
            return self._hinting_at_the_bad_port(request)

        self._serving(monkeypatch, handler)
        server = await mcp_oauth.discover(self._SERVER)

        assert server.token_endpoint == "https://93.184.216.35/token"
        assert server.authorization_endpoint == "https://93.184.216.35/authorize"

    @pytest.mark.anyio
    async def test_a_token_endpoint_discovery_accepted_but_httpx_will_not_build(
        self, monkeypatch, caplog
    ):
        """`AnyHttpUrl` has no length limit and `httpx` stops at 64 KiB, which
        is how an endpoint the metadata document was validated with reaches the
        vault and comes back at every refresh. The refresh path answers `None`
        on an `OAuthError` and a 500 on anything else."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/.well-known/oauth-protected-resource":
                return httpx.Response(
                    200,
                    json={
                        "resource": "https://93.184.216.34/mcp",
                        "authorization_servers": ["https://93.184.216.35"],
                    },
                )
            if request.url.path == "/.well-known/oauth-authorization-server":
                return httpx.Response(200, json=self._metadata(self._TOO_LONG))
            return httpx.Response(404, json={})

        self._serving(monkeypatch, handler)
        server = await mcp_oauth.discover(self._SERVER)
        assert server.token_endpoint == self._TOO_LONG

        with (
            caplog.at_level(logging.WARNING, logger="app.agents.mcp_oauth"),
            pytest.raises(mcp_oauth.OAuthError) as exc_info,
        ):
            await mcp_oauth._token_request(server.token_endpoint, {"grant_type": "refresh_token"})

        assert "a token endpoint" in str(exc_info.value)
        assert "URL too long" in caplog.text

    @pytest.mark.anyio
    async def test_a_registration_endpoint_no_request_can_be_built_for_is_refused(self):
        """`create_client_registration_request` sits above the client, so this
        one raised before the flow's `except httpx.HTTPError` was even entered."""
        metadata = OAuthMetadata(
            issuer=AnyUrl("https://auth.example.com"),
            authorization_endpoint=AnyUrl("https://auth.example.com/authorize"),
            token_endpoint=AnyUrl("https://auth.example.com/token"),
            registration_endpoint=AnyUrl(self._TOO_LONG),
            response_types_supported=["code"],
        )
        server = mcp_oauth.DiscoveredServer(
            authorization_endpoint=str(metadata.authorization_endpoint),
            token_endpoint=str(metadata.token_endpoint),
            registration_endpoint=str(metadata.registration_endpoint),
            resource="https://mcp.example.com/",
            scope=None,
            metadata=metadata,
        )
        with pytest.raises(mcp_oauth.OAuthError) as exc_info:
            await mcp_oauth.register_client(server, "https://app.example.com/oauth/callback")

        assert "a registration endpoint" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_the_refusal_does_not_quote_the_port_it_could_not_parse(self, caplog):
        """`InvalidURL` says `Invalid port: 'client_secret=sh-9f2c'`, and on this
        flow that string was written by the server being refused. It stays in
        the log; the browser is told which endpoint was unusable and no more."""
        endpoint = "https://auth.example.com:client_secret=sh-9f2c/token"
        with (
            caplog.at_level(logging.WARNING, logger="app.agents.mcp_oauth"),
            pytest.raises(mcp_oauth.OAuthError) as exc_info,
        ):
            await mcp_oauth._token_request(endpoint, {"grant_type": "authorization_code"})

        shown = str(exc_info.value)
        assert "sh-9f2c" not in shown
        assert "auth.example.com" not in shown
        assert "sh-9f2c" in caplog.text


class TestReadSchema:
    def test_token_never_leaves_backend(self):
        conn = _connection()
        conn.auth_token = _seal_into(conn, "secret")
        read = McpConnectionRead.from_model(conn)
        assert read.has_auth_token is True
        assert "secret" not in read.model_dump_json()

    def test_oauth_authorized_reflects_tokens_and_pending_state(self):
        # First-time consent not completed: only a pending flow → not authorized.
        pending = _connection(auth_type="oauth", oauth_state="s")
        pending.oauth_pending_payload = _seal_into(
            pending, _base_payload(code_verifier="v").model_dump_json()
        )
        assert McpConnectionRead.from_model(pending).oauth_authorized is False
        # Completed: tokens present → authorized.
        done = _oauth_connection(_base_payload(access_token="AT"), oauth_state=None)
        read = McpConnectionRead.from_model(done)
        assert read.oauth_authorized is True
        assert read.auth_type == "oauth"
        # The encrypted payload (with tokens) never appears in the response.
        assert "AT" not in read.model_dump_json()

    def test_reauthorizing_a_live_connection_still_reads_as_connected(self):
        """A re-authorization in flight must not flash "not connected" in the UI
        for a connection whose tokens still work."""
        conn = _oauth_connection(_base_payload(access_token="AT"), oauth_state="new-flow")
        conn.oauth_pending_payload = _seal_into(
            conn, _base_payload(code_verifier="v").model_dump_json()
        )
        assert McpConnectionRead.from_model(conn).oauth_authorized is True
