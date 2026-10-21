"""Connected accounts (#2191): a Google grant a virtual terminal's mount signs in as.

They ride on the MCP connection table's OAuth machinery - the consent staging, the
shared callback, the sealed payload - so what is tested here is what is new: who
owns the account, what it is named once Google says, a re-consent folding into the
grant it replaces, and what a run is handed.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from app.agents.mcp_oauth import McpOAuthPayload
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import GoogleOAuthAppSecret
from app.core.vault import seal
from app.db.models.mcp_connection import McpConnection
from app.services import mcp_connection as service_module
from app.services.mcp_connection import McpConnectionService, connection_scope
from app.services.portals import google_oauth

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx() -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")


@pytest.fixture
def repo(monkeypatch) -> MagicMock:
    mock = MagicMock()
    mock.create = AsyncMock()
    mock.create_org_scoped = AsyncMock()
    mock.update = AsyncMock(side_effect=lambda db, *, db_connection, update_data: db_connection)
    mock.delete = AsyncMock()
    mock.list_accounts = AsyncMock(return_value=[])
    mock.get_account = AsyncMock(return_value=None)
    monkeypatch.setattr(service_module, "mcp_connection_repo", mock)
    return mock


@pytest.fixture
def client(monkeypatch) -> GoogleOAuthAppSecret:
    creds = GoogleOAuthAppSecret(client_id="org-client", client_secret="org-secret")
    monkeypatch.setattr(
        service_module.OrganizationSecretService, "oauth_app", AsyncMock(return_value=creds)
    )
    return creds


def _account(**overrides) -> McpConnection:
    fields = {
        "id": uuid4(),
        "user_id": uuid4(),
        "organization_id": None,
        "scope": "user",
        "catalog_key": "google",
        "purpose": "account",
        "name": "google-account-x",
        "label": None,
        "url": "https://www.googleapis.com",
        "secret_key_version": 1,
        "auth_type": "oauth",
        "oauth_payload": None,
        "granted_scopes": None,
        "last_status": None,
        "last_error": None,
        "created_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return McpConnection(**fields)


def _payload(**overrides) -> McpOAuthPayload:
    data = {
        "server_url": "https://www.googleapis.com",
        "started_at": datetime.now(UTC).timestamp(),
        "authorization_endpoint": google_oauth.AUTHORIZE_ENDPOINT,
        "token_endpoint": google_oauth.TOKEN_ENDPOINT,
        "client_id": "org-client",
        "client_secret": "org-secret",
        "resource": "https://www.googleapis.com",
        "redirect_uri": "https://app/api/me/mcp-connections/oauth/callback",
        "provider": "google",
        "access_token": "AT",
        "refresh_token": "RT",
    }
    data.update(overrides)
    return McpOAuthPayload(**data)


def _sealed(account: McpConnection, payload: McpOAuthPayload) -> str:
    return seal(
        payload.model_dump_json(),
        scope=connection_scope(account),
        key_version=account.secret_key_version,
    ).ciphertext


# -- connecting --------------------------------------------------------------


@pytest.mark.parametrize("for_organization", [False, True])
async def test_connecting_asks_google_for_every_service_with_the_orgs_client(
    ctx, repo, client, for_organization
):
    url = await McpConnectionService(AsyncMock()).account_start(
        ctx, for_organization=for_organization
    )

    assert url.startswith(google_oauth.AUTHORIZE_ENDPOINT)
    assert "client_id=org-client" in url and "org-secret" not in url
    assert "drive" in url and "gmail.modify" in url and "access_type=offline" in url
    create = repo.create_org_scoped if for_organization else repo.create
    written = create.await_args.kwargs
    assert written["purpose"] == "account" and written["catalog_key"] == "google"
    assert written["name"].startswith("google-account-")
    if for_organization:
        assert written["organization_id"] == ctx.organization_id
    else:
        assert written["user_id"] == ctx.subject_id


async def test_an_impersonating_administrator_cannot_connect_as_the_member(
    ctx, repo, client, monkeypatch
):
    monkeypatch.setattr(
        service_module,
        "refuse_binding_while_impersonating",
        MagicMock(side_effect=AuthorizationError(message="not while impersonating")),
    )
    with pytest.raises(AuthorizationError):
        await McpConnectionService(AsyncMock()).account_start(ctx, for_organization=False)
    repo.create.assert_not_called()


# -- the callback names the account ------------------------------------------


async def test_a_new_account_is_named_by_its_address(repo, monkeypatch):
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ana@acme.com"))
    account = _account()

    named = await McpConnectionService(AsyncMock())._name_account(account, "AT")

    update = repo.update.await_args.kwargs["update_data"]
    assert update == {"label": "ana@acme.com", "name": "google:ana@acme.com"}
    assert named is account


async def test_an_address_google_will_not_say_still_gets_a_name(repo, monkeypatch):
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value=None))
    await McpConnectionService(AsyncMock())._name_account(_account(), "AT")
    assert repo.update.await_args.kwargs["update_data"]["label"] == "Google account"


async def test_a_re_consent_folds_into_the_grant_the_address_already_has(repo, monkeypatch):
    """The same address connected twice is one account with the newer grant, not two
    folders of the same mailbox."""
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ana@acme.com"))
    owner = uuid4()
    earlier = _account(user_id=owner, label="ana@acme.com", name="google:ana@acme.com")
    fresh = _account(user_id=owner, granted_scopes=[google_oauth.DRIVE])
    fresh.oauth_payload = _sealed(fresh, _payload(refresh_token="NEW"))
    repo.list_accounts = AsyncMock(return_value=[earlier, fresh])

    kept = await McpConnectionService(AsyncMock())._name_account(fresh, "AT")

    assert kept is earlier
    update = repo.update.await_args.kwargs["update_data"]
    assert update["granted_scopes"] == [google_oauth.DRIVE] and update["last_status"] == "ok"
    assert update["oauth_payload"] != earlier.oauth_payload
    repo.delete.assert_awaited_once()
    assert repo.delete.await_args.kwargs["db_connection"] is fresh
    assert repo.list_accounts.await_args.kwargs["user_id"] == owner


async def test_an_unreadable_new_grant_leaves_the_earlier_one_as_it_was(repo, monkeypatch):
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ops@acme.com"))
    org = uuid4()
    earlier = _account(
        user_id=None, scope="org", organization_id=org, label="ops@acme.com", oauth_payload="kept"
    )
    fresh = _account(user_id=None, scope="org", organization_id=org, oauth_payload="garbage")
    repo.list_accounts = AsyncMock(return_value=[earlier, fresh])

    await McpConnectionService(AsyncMock())._name_account(fresh, "AT")

    assert repo.update.await_args.kwargs["update_data"]["oauth_payload"] == "kept"
    assert repo.list_accounts.await_args.kwargs["organization_id"] == org


async def test_the_shared_callback_names_an_account_rather_than_probing_it(repo, monkeypatch):
    pending = _account(oauth_state="state")
    pending.oauth_pending_payload = _sealed(
        pending, _payload(access_token=None, refresh_token=None)
    )
    repo.get_by_oauth_state = AsyncMock(return_value=pending)
    monkeypatch.setattr(
        google_oauth,
        "exchange_code",
        AsyncMock(
            return_value=google_oauth.GoogleToken(
                access_token="AT",
                refresh_token="RT",
                expires_in=3600,
                granted_scopes=[google_oauth.DRIVE],
            )
        ),
    )
    name = AsyncMock(return_value=pending)
    monkeypatch.setattr(McpConnectionService, "_name_account", name)
    probe = AsyncMock()
    monkeypatch.setattr(McpConnectionService, "_probe", probe)

    await McpConnectionService(AsyncMock()).oauth_callback(state="state", code="code")

    name.assert_awaited_once()
    assert name.await_args.args[1] == "AT"
    probe.assert_not_called()


# -- listing, disconnecting, and what a run gets ------------------------------


@pytest.mark.parametrize("for_organization", [False, True])
async def test_the_owner_lists_their_accounts_and_nobody_elses(ctx, repo, for_organization):
    await McpConnectionService(AsyncMock()).list_accounts(ctx, for_organization=for_organization)
    asked = repo.list_accounts.await_args.kwargs
    if for_organization:
        assert asked["organization_id"] == ctx.organization_id and asked["user_id"] is None
    else:
        assert asked["user_id"] == ctx.subject_id and asked["organization_id"] is None


async def test_an_account_is_disconnected_only_by_its_owner(ctx, repo):
    service = McpConnectionService(AsyncMock())
    mine = _account(user_id=ctx.subject_id)
    orgs = _account(user_id=None, scope="org", organization_id=ctx.organization_id)

    repo.get_account = AsyncMock(return_value=mine)
    await service.delete_account(ctx, mine.id, for_organization=False)
    repo.get_account = AsyncMock(return_value=orgs)
    await service.delete_account(ctx, orgs.id, for_organization=True)
    assert repo.delete.await_count == 2

    for account, for_organization in [
        (_account(), False),
        (mine, True),
        (_account(user_id=None, scope="org", organization_id=uuid4()), True),
        (None, False),
    ]:
        repo.get_account = AsyncMock(return_value=account)
        with pytest.raises(NotFoundError):
            await service.delete_account(ctx, uuid4(), for_organization=for_organization)


async def test_a_run_is_handed_the_refresh_token_and_its_client():
    account = _account(label="ana@acme.com", granted_scopes=[google_oauth.DRIVE])
    account.oauth_payload = _sealed(account, _payload())

    grant = await McpConnectionService(AsyncMock()).account_grant(account)

    assert grant is not None and grant.email == "ana@acme.com"
    assert grant.client_id == "org-client" and grant.refresh_token.get_secret_value() == "RT"
    assert grant.scopes == frozenset({google_oauth.DRIVE})
    assert "RT" not in repr(grant)


async def test_a_grant_without_a_refresh_token_cannot_be_mounted():
    account = _account()
    account.oauth_payload = _sealed(account, _payload(refresh_token=None))
    assert await McpConnectionService(AsyncMock()).account_grant(account) is None
    account.oauth_payload = None
    assert await McpConnectionService(AsyncMock()).account_grant(account) is None


# -- the address, from Google ---------------------------------------------------


def _google(handler) -> None:
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def client(*args, **kwargs):
        return original(*args, transport=transport, **kwargs)

    return client


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, json={"email": "ana@acme.com"}), "ana@acme.com"),
        (httpx.Response(200, json={"name": "Ana"}), None),
        (httpx.Response(200, json=["x"]), None),
        (httpx.Response(200, text="not json"), None),
        (httpx.Response(401, json={"error": "invalid"}), None),
    ],
)
async def test_the_address_is_read_from_googles_userinfo(monkeypatch, response, expected):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _google(handler))
    assert await google_oauth.account_email("AT") == expected
    assert seen[0].headers["authorization"] == "Bearer AT"


async def test_an_unreachable_google_has_no_address(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(google_oauth.httpx, "AsyncClient", _google(handler))
    assert await google_oauth.account_email("AT") is None


def test_the_read_says_whose_account_it_is_and_never_a_token():
    from app.schemas.connected_account import ConnectedAccountRead

    account = _account(
        label="ana@acme.com", granted_scopes=[google_oauth.GMAIL, google_oauth.DRIVE]
    )
    account.oauth_payload = "sealed"
    read = ConnectedAccountRead.from_model(account)
    assert read.email == "ana@acme.com" and read.owner == "personal"
    assert read.scopes == sorted([google_oauth.GMAIL, google_oauth.DRIVE])
    assert "sealed" not in read.model_dump_json()
    unnamed = ConnectedAccountRead.from_model(
        _account(scope="org", user_id=None, organization_id=uuid4())
    )
    assert unnamed.email == "google-account-x" and unnamed.owner == "organization"
