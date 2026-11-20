"""Connected accounts (#2191): a Google grant a virtual terminal's mount signs in as.

They ride on the MCP connection table's OAuth machinery - the consent staging, the
shared callback, the sealed payload - so what is tested here is what is new: who
owns the account, what it is named once Google says, a re-consent folding into the
grant it replaces, and what a run is handed.
"""

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
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

pytestmark = [pytest.mark.anyio, pytest.mark.security]
NONCE = "n" * 43
INITIATOR = uuid4()
SOURCE_ORG = uuid4()
SOURCE_SECRET = uuid4()
SOURCE_GENERATION = uuid4()


@pytest.fixture(autouse=True)
def live_source(monkeypatch):
    from app.repositories import member_repo, organization_secret_repo

    monkeypatch.setattr(
        service_module,
        "decider_context",
        AsyncMock(
            return_value=AuthContext(user_id=INITIATOR, organization_id=SOURCE_ORG, role="owner")
        ),
    )
    monkeypatch.setattr(
        organization_secret_repo,
        "authorization_generation",
        AsyncMock(return_value=SOURCE_GENERATION),
    )
    monkeypatch.setattr(service_module, "record_audit", AsyncMock())
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=MagicMock(role="owner")))


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
    mock.get_pending_account = AsyncMock(return_value=None)
    mock.lock_account_owner = AsyncMock()
    monkeypatch.setattr(service_module, "mcp_connection_repo", mock)
    return mock


@pytest.fixture(autouse=True)
def org_google_app(monkeypatch) -> GoogleOAuthAppSecret:
    """The organization's Google app, as a consent or a refresh reads it.

    Patched at `oauth_app_identity_for_org`, which `oauth_app_identity` delegates to
    and which a refresh of an org-referenced grant calls directly.
    """
    creds = GoogleOAuthAppSecret(client_id="org-client", client_secret="org-secret")
    monkeypatch.setattr(
        service_module.OrganizationSecretService,
        "oauth_app_identity_for_org",
        AsyncMock(return_value=(creds, SOURCE_SECRET, SOURCE_GENERATION)),
    )
    return creds


@pytest.fixture
def client(org_google_app) -> GoogleOAuthAppSecret:
    return org_google_app


def _account(**overrides) -> McpConnection:
    fields = {
        "id": uuid4(),
        "user_id": uuid4(),
        "organization_id": None,
        "account_source_organization_id": SOURCE_ORG,
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
        "browser_nonce_digest": hashlib.sha256(NONCE.encode()).hexdigest(),
        "account_initiator_id": INITIATOR,
        "account_source_organization_id": SOURCE_ORG,
        "account_source_secret_id": SOURCE_SECRET,
        "account_source_generation": SOURCE_GENERATION,
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
        ctx, for_organization=for_organization, browser_nonce=NONCE
    )

    assert url.startswith(google_oauth.AUTHORIZE_ENDPOINT)
    assert "client_id=org-client" in url and "org-secret" not in url
    requested_scopes = set(parse_qs(urlparse(url).query)["scope"][0].split())
    assert google_oauth.DRIVE_READONLY in requested_scopes
    assert google_oauth.DRIVE not in requested_scopes
    assert google_oauth.GMAIL in requested_scopes and "access_type=offline" in url
    create = repo.create_org_scoped if for_organization else repo.create
    written = create.await_args.kwargs
    assert written["purpose"] == "account" and written["catalog_key"] == "google"
    assert written["name"].startswith("google-account-")
    assert written["account_source_organization_id"] == ctx.organization_id
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
        await McpConnectionService(AsyncMock()).account_start(
            ctx, for_organization=False, browser_nonce=NONCE
        )
    repo.create.assert_not_called()


@pytest.mark.parametrize("for_organization", [False, True])
async def test_abandoned_account_consent_can_restart_after_its_master_key_is_removed(
    ctx: AuthContext,
    repo: MagicMock,
    client: GoogleOAuthAppSecret,
    monkeypatch: pytest.MonkeyPatch,
    for_organization: bool,
) -> None:
    from app.core.config import settings
    from app.core.vault import unseal

    pending = _account(
        scope="org" if for_organization else "user",
        user_id=None if for_organization else ctx.subject_id,
        organization_id=ctx.organization_id if for_organization else None,
        secret_key_version=1,
        oauth_pending_payload="old-unreadable-consent",
    )
    repo.get_pending_account.return_value = pending
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {2: "replacement-test-master-key"})

    url = await McpConnectionService(AsyncMock()).account_start(
        ctx, for_organization=for_organization, browser_nonce=NONCE
    )

    assert url.startswith(google_oauth.AUTHORIZE_ENDPOINT)
    written = repo.update.await_args.kwargs["update_data"]
    assert written["secret_key_version"] == 2
    payload = McpOAuthPayload.model_validate_json(
        unseal(
            written["oauth_pending_payload"],
            scope=connection_scope(pending),
            key_version=written["secret_key_version"],
        )
    )
    assert payload.client_id == client.client_id
    assert payload.account_initiator_id == ctx.subject_id
    assert payload.browser_nonce_digest == hashlib.sha256(NONCE.encode()).hexdigest()
    assert payload.access_token is None and payload.refresh_token is None
    assert "oauth_payload" not in written
    repo.create.assert_not_awaited()
    repo.create_org_scoped.assert_not_awaited()


# -- the callback names the account ------------------------------------------


async def test_a_new_account_is_named_by_its_address(repo, monkeypatch):
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ana@acme.com"))
    account = _account()

    named = await McpConnectionService(AsyncMock())._name_account(account, "AT")

    update = repo.update.await_args.kwargs["update_data"]
    assert update == {
        "account_source_organization_id": SOURCE_ORG,
        "account_email": "ana@acme.com",
        "label": "ana@acme.com",
        "name": f"google-account-{account.id.hex}",
    }
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

    with pytest.raises(service_module.OAuthError, match="cannot be read"):
        await McpConnectionService(AsyncMock())._name_account(fresh, "AT")

    repo.update.assert_not_awaited()
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

    await McpConnectionService(AsyncMock()).oauth_callback(
        state="state", code="code", browser_nonce=NONCE, acting_user_id=INITIATOR
    )

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

    grant = await McpConnectionService(AsyncMock()).account_grant(
        account, organization_id=SOURCE_ORG
    )

    assert grant is not None and grant.email == "ana@acme.com"
    assert grant.client_id == "org-client" and grant.refresh_token.get_secret_value() == "RT"
    assert grant.scopes == frozenset({google_oauth.DRIVE})
    assert "RT" not in repr(grant)


async def test_a_grant_without_a_refresh_token_cannot_be_mounted():
    account = _account()
    account.oauth_payload = _sealed(account, _payload(refresh_token=None))
    assert (
        await McpConnectionService(AsyncMock()).account_grant(account, organization_id=SOURCE_ORG)
        is None
    )
    account.oauth_payload = None
    assert (
        await McpConnectionService(AsyncMock()).account_grant(account, organization_id=SOURCE_ORG)
        is None
    )


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
        (
            httpx.Response(200, json={"email": "ana@acme.com", "email_verified": True}),
            "ana@acme.com",
        ),
        (httpx.Response(200, json={"name": "Ana"}), None),
        (httpx.Response(200, json={"email": "ana@acme.com", "email_verified": False}), None),
        (httpx.Response(200, json={"email": "ana@acme.com"}), None),
        (httpx.Response(200, json={"email": "not-an-email", "email_verified": True}), None),
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


async def test_unidentified_accounts_do_not_overwrite_an_existing_unknown_grant(repo, monkeypatch):
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value=None))
    old = _account(label="Google account", oauth_payload="old-grant")
    fresh = _account(user_id=old.user_id)
    repo.list_accounts.return_value = [old, fresh]
    await McpConnectionService(AsyncMock())._name_account(fresh, "AT")
    repo.delete.assert_not_awaited()
    assert repo.update.await_args.kwargs["db_connection"] is fresh


async def test_a_long_email_has_a_short_label_and_a_complete_identity(repo, monkeypatch):
    email = "a" * 64 + "@a-long-workspace-domain.example.com"
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value=email))
    await McpConnectionService(AsyncMock())._name_account(_account(), "AT")
    update = repo.update.await_args.kwargs["update_data"]
    assert update["account_email"] == email
    assert len(update["label"]) == 64 and len(update["name"]) <= 64


@pytest.mark.parametrize(
    "nonce,actor", [(None, INITIATOR), ("wrong", INITIATOR), (NONCE, None), (NONCE, uuid4())]
)
async def test_account_consent_requires_the_starting_browser_and_identity(
    repo, nonce, actor, monkeypatch
):
    pending = _account(oauth_state="state")
    pending.oauth_pending_payload = _sealed(pending, _payload(access_token=None))
    repo.get_by_oauth_state = AsyncMock(return_value=pending)
    exchange = AsyncMock()
    monkeypatch.setattr(google_oauth, "exchange_code", exchange)
    with pytest.raises(service_module.OAuthError, match="browser and account"):
        await McpConnectionService(AsyncMock()).oauth_callback(
            state="state", code="code", browser_nonce=nonce, acting_user_id=actor
        )
    exchange.assert_not_awaited()


async def test_an_abandoned_consent_is_reused(ctx, repo, client):
    pending = _account(user_id=ctx.subject_id, auth_type="oauth")
    repo.get_pending_account.return_value = pending
    await McpConnectionService(AsyncMock()).account_start(
        ctx, for_organization=False, browser_nonce=NONCE
    )
    repo.create.assert_not_awaited()
    assert repo.update.await_args.kwargs["db_connection"] is pending


async def test_a_connected_account_is_not_editable_through_the_mcp_server_routes(repo):
    account = _account()
    repo.get_by_id_for_update = AsyncMock(return_value=account)
    with pytest.raises(NotFoundError):
        await McpConnectionService(AsyncMock())._get_owned(
            user_id=account.user_id, connection_id=account.id, for_update=True
        )


async def test_a_revoked_grant_is_not_handed_to_a_mount():
    from app.db.models.mcp_connection import AUTHORIZATION_EXPIRED

    account = _account(last_status="error", last_error=AUTHORIZATION_EXPIRED)
    account.oauth_payload = _sealed(account, _payload())
    assert (
        await McpConnectionService(AsyncMock()).account_grant(account, organization_id=SOURCE_ORG)
        is None
    )


async def test_reconnecting_an_unreadable_old_key_rekeys_the_preserved_account(repo, monkeypatch):
    from app.core.config import settings
    from app.core.vault import unseal

    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {2: "replacement-test-master-key"})
    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ana@acme.com"))
    owner = uuid4()
    earlier = _account(
        user_id=owner,
        account_email="ana@acme.com",
        secret_key_version=1,
        oauth_payload="unreadable-old-envelope",
    )
    fresh = _account(user_id=owner, secret_key_version=2)
    fresh.oauth_payload = _sealed(fresh, _payload(refresh_token="replacement-refresh-token"))
    repo.list_accounts = AsyncMock(return_value=[earlier, fresh])
    kept = await McpConnectionService(AsyncMock())._name_account(fresh, "AT")
    assert kept is earlier
    update = repo.update.await_args.kwargs["update_data"]
    assert update["secret_key_version"] == 2
    assert update["oauth_pending_payload"] is None and update["auth_token"] is None
    recovered = McpOAuthPayload.model_validate_json(
        unseal(update["oauth_payload"], scope=connection_scope(earlier), key_version=2)
    )
    assert recovered.refresh_token is not None
    assert recovered.refresh_token.get_secret_value() == "replacement-refresh-token"


@pytest.mark.parametrize("role", [None, "viewer", "owner"])
async def test_org_consent_rechecks_current_authority_before_exchanging_a_code(
    repo, monkeypatch, role
):
    org = uuid4()
    pending = _account(scope="org", user_id=None, organization_id=org, oauth_state="state")
    pending.oauth_pending_payload = _sealed(
        pending, _payload(access_token=None, refresh_token=None, account_source_organization_id=org)
    )
    repo.get_by_oauth_state = AsyncMock(return_value=pending)
    context = (
        None if role is None else AuthContext(user_id=INITIATOR, organization_id=org, role=role)
    )
    authority = AsyncMock(return_value=context)
    monkeypatch.setattr(service_module, "decider_context", authority)
    exchange = AsyncMock(
        return_value=(_payload(account_source_organization_id=org), [google_oauth.DRIVE])
    )
    monkeypatch.setattr(service_module, "_complete_google_flow", exchange)
    monkeypatch.setattr(McpConnectionService, "_name_account", AsyncMock(return_value=pending))
    if role == "owner":
        await McpConnectionService(AsyncMock()).oauth_callback(
            state="state", code="code", browser_nonce=NONCE, acting_user_id=INITIATOR
        )
        exchange.assert_awaited_once()
    else:
        with pytest.raises(service_module.OAuthError, match="organization access changed"):
            await McpConnectionService(AsyncMock()).oauth_callback(
                state="state", code="code", browser_nonce=NONCE, acting_user_id=INITIATOR
            )
        exchange.assert_not_awaited()
        repo.update.assert_not_awaited()
    assert authority.await_count == 1
    assert authority.await_args.kwargs == {"organization_id": org, "user_id": INITIATOR}


@pytest.mark.parametrize("readable", [True, False])
async def test_reconsent_without_a_new_refresh_token_preserves_only_a_readable_old_one(
    repo, monkeypatch, readable
):
    from app.core.vault import unseal

    monkeypatch.setattr(google_oauth, "account_email", AsyncMock(return_value="ana@acme.com"))
    owner = uuid4()
    earlier = _account(user_id=owner, account_email="ana@acme.com")
    earlier.oauth_payload = (
        _sealed(earlier, _payload(refresh_token="OLD")) if readable else "unreadable"
    )
    fresh = _account(user_id=owner)
    fresh.oauth_payload = _sealed(fresh, _payload(refresh_token=None))
    repo.list_accounts.return_value = [earlier, fresh]

    assert await McpConnectionService(AsyncMock())._name_account(fresh, "AT") is earlier
    update = repo.update.await_args.kwargs["update_data"]
    recovered = McpOAuthPayload.model_validate_json(
        unseal(
            update["oauth_payload"],
            scope=connection_scope(earlier),
            key_version=update["secret_key_version"],
        )
    )
    if readable:
        assert recovered.refresh_token is not None
        assert recovered.refresh_token.get_secret_value() == "OLD"
    else:
        assert recovered.refresh_token is None


@pytest.mark.parametrize("removed", [True, False])
async def test_callback_rechecks_that_consent_is_pending_after_obtaining_the_owner_lock(
    repo, removed
):
    pending = _account(oauth_state="state")
    pending.oauth_pending_payload = _sealed(pending, _payload(access_token=None))
    completed = _account(oauth_state="state", oauth_pending_payload=None)
    repo.get_by_oauth_state = AsyncMock(side_effect=[pending, None if removed else completed])

    with pytest.raises(NotFoundError, match="already completed"):
        await McpConnectionService(AsyncMock()).oauth_callback(
            state="state", code="code", browser_nonce=NONCE, acting_user_id=INITIATOR
        )
    repo.lock_account_owner.assert_awaited_once()
    repo.update.assert_not_awaited()


async def test_legacy_pending_personal_consent_cannot_survive_membership_recreation(
    repo, monkeypatch
):
    pending = _account(account_source_organization_id=None, oauth_state="state")
    pending.oauth_pending_payload = _sealed(
        pending, _payload(access_token=None, refresh_token=None)
    )
    repo.get_by_oauth_state = AsyncMock(return_value=pending)
    exchange = AsyncMock()
    monkeypatch.setattr(service_module, "_complete_google_flow", exchange)
    with pytest.raises(service_module.OAuthError, match="start consent again"):
        await McpConnectionService(AsyncMock()).oauth_callback(
            state="state", code="old-code", browser_nonce=NONCE, acting_user_id=INITIATOR
        )
    exchange.assert_not_awaited()


async def test_account_start_rechecks_membership_under_the_account_owner_lock(
    ctx, repo, client, monkeypatch
):
    from app.repositories import member_repo

    async def membership(*args, **kwargs):
        repo.lock_account_owner.assert_awaited_once()
        return

    monkeypatch.setattr(member_repo, "get_active", membership)
    with pytest.raises(AuthorizationError, match="current organization membership"):
        await McpConnectionService(AsyncMock()).account_start(
            ctx, for_organization=False, browser_nonce=NONCE
        )
    repo.create.assert_not_awaited()
    repo.get_pending_account.assert_not_awaited()
