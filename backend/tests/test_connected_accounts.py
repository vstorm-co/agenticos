"""Connected accounts (#2191): a Google grant a virtual terminal's mount signs in as.

They ride on the MCP connection table's OAuth machinery - the consent staging, the
shared callback, the sealed payload - so what is tested here is what is new: who
owns the account, what it is named once Google says, a re-consent folding into the
grant it replaces, and what a run is handed.
"""

import hashlib
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
    monkeypatch.setattr(
        "app.services.agent_trigger.AgentTriggerService.release_polled_connection", AsyncMock()
    )
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


@pytest.fixture
def client(monkeypatch) -> GoogleOAuthAppSecret:
    creds = GoogleOAuthAppSecret(client_id="org-client", client_secret="org-secret")
    monkeypatch.setattr(
        service_module.OrganizationSecretService,
        "oauth_app_identity",
        AsyncMock(return_value=(creds, SOURCE_SECRET, SOURCE_GENERATION)),
    )
    return creds


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
    assert "drive" in url and "gmail.modify" in url and "access_type=offline" in url
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


@pytest.fixture
def native_repo(repo, ctx, monkeypatch):
    monkeypatch.setattr("app.services.integrations.service.mcp_connection_repo", repo)

    async def create(db, **fields):
        organization_id = fields.get("organization_id")
        return _account(
            scope="org" if organization_id else "user",
            organization_id=organization_id,
            user_id=None if organization_id else ctx.user_id,
            catalog_key=fields["catalog_key"],
            name=fields["name"],
            label=fields.get("label"),
            url=fields["url"],
            auth_type=fields.get("auth_type", "bearer"),
            auth_token=fields.get("auth_token") or fields.get("sealed_token"),
            secret_key_version=fields["secret_key_version"],
            account_source_organization_id=ctx.organization_id,
            is_enabled=True,
        )

    async def update(db, *, db_connection, update_data):
        for key, value in update_data.items():
            setattr(db_connection, key, value)
        return db_connection

    repo.create.side_effect = repo.create_org_scoped.side_effect = create
    repo.update.side_effect = update
    return repo


@pytest.mark.parametrize("provider", ["google", "microsoft", "slack"])
@pytest.mark.parametrize("write", [False, True])
async def test_native_consent_matches_the_setup_scopes_and_provider_client(
    ctx, native_repo, client, monkeypatch, provider, write
):
    from urllib.parse import parse_qs, urlsplit

    from app.core.secret_kinds import MicrosoftOAuthAppSecret, SlackOAuthAppSecret
    from app.services.integrations import setup_for

    credentials = (
        client
        if provider == "google"
        else MicrosoftOAuthAppSecret(
            client_id="00000000-0000-0000-0000-000000000001",
            client_secret="client-secret",
            tenant_id="common",
        )
        if provider == "microsoft"
        else SlackOAuthAppSecret(client_id="client", client_secret="client-secret")
    )
    monkeypatch.setattr(
        service_module.OrganizationSecretService,
        "oauth_app_identity",
        AsyncMock(return_value=(credentials, SOURCE_SECRET, SOURCE_GENERATION)),
    )
    product = {"google": "gmail", "microsoft": "outlook_mail", "slack": "slack"}[provider]
    info = setup_for(provider, write=write)
    selected = next(item for item in info.products if item.id == product)
    result = await McpConnectionService(MagicMock()).account_start(
        ctx,
        for_organization=False,
        browser_nonce=NONCE,
        provider=provider,
        products=[product],
        write=write,
    )
    query = parse_qs(urlsplit(result).query)
    actual = (
        set(query["user_scope"][0].split(","))
        if provider == "slack"
        else set(query["scope"][0].split())
    )
    assert actual == set(
        info.identity_scopes + selected.read_scopes + (selected.write_scopes if write else [])
    )
    assert query["redirect_uri"] == [info.redirect_uri]
    if provider == "google":
        assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]


@pytest.mark.parametrize("for_organization", [False, True])
async def test_slack_token_connect_validates_then_seals_a_named_workspace_account(
    ctx, native_repo, monkeypatch, for_organization
):
    from pydantic import SecretStr

    monkeypatch.setattr(
        service_module.slack_oauth,
        "identify",
        AsyncMock(return_value=("Workspace / member", ["chat:write"])),
    )
    service = McpConnectionService(MagicMock())
    row = await service.connect_slack_token(
        ctx,
        token=SecretStr("xoxp-private-token"),
        label="Client workspace",
        for_organization=for_organization,
    )
    assert row.catalog_key == "slack" and row.label == "Client workspace"
    assert row.granted_scopes == ["chat:write"]
    assert row.auth_token != "xoxp-private-token"
    assert (
        await service.integration_access_token(row, organization_id=ctx.organization_id)
    ).get_secret_value() == "xoxp-private-token"
    assert await service.integration_access_token(row, organization_id=uuid4()) is None
    row.is_enabled = False
    assert await service.integration_access_token(row, organization_id=ctx.organization_id) is None


async def test_slack_token_connect_requires_a_real_token_and_current_membership(
    ctx, native_repo, monkeypatch
):
    from pydantic import SecretStr

    from app.core.exceptions import BadRequestError
    from app.repositories import member_repo

    service = McpConnectionService(MagicMock())
    with pytest.raises(BadRequestError):
        await service.connect_slack_token(
            ctx, token=SecretStr("wrong-token"), label="", for_organization=False
        )
    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await service.connect_slack_token(
            ctx, token=SecretStr("xoxb-private-token"), label="", for_organization=True
        )
    native_repo.create_org_scoped.assert_not_awaited()


@pytest.mark.parametrize(
    "provider,products,subject",
    [
        ("google", ["gmail"], "person@example.com"),
        ("microsoft", ["outlook_mail"], "person@example.com"),
        ("microsoft", ["teams"], "00000000-0000-0000-0000-000000000001"),
    ],
)
@pytest.mark.parametrize("for_organization", [False, True])
async def test_application_accounts_revalidate_the_source_credential_before_minting_tokens(
    ctx, native_repo, monkeypatch, provider, products, subject, for_organization
):
    from pydantic import SecretStr

    source = MagicMock(
        id=SOURCE_SECRET, name="Automation", authorization_generation=SOURCE_GENERATION
    )
    monkeypatch.setattr(
        service_module.OrganizationSecretService, "get_usable", AsyncMock(return_value=source)
    )
    token = AsyncMock(return_value=SecretStr("provider-access-token"))
    monkeypatch.setattr(service_module.OrganizationSecretService, "integration_token", token)
    service = McpConnectionService(MagicMock())
    row = await service.connect_application_account(
        ctx,
        provider=provider,
        secret_id=SOURCE_SECRET,
        subject=subject,
        products=products,
        write=True,
        label="Automation",
        for_organization=for_organization,
    )
    assert row.auth_type == "application" and row.account_email == subject
    assert "provider-access-token" not in row.oauth_payload
    assert await service.integration_access_token(
        row, organization_id=ctx.organization_id
    ) == SecretStr("provider-access-token")
    assert (
        token.await_args.kwargs["provider"] == provider
        and token.await_args.kwargs["subject"] == subject
    )
    assert await service.integration_access_token(row, organization_id=uuid4()) is None


@pytest.mark.parametrize(
    "provider,products,subject",
    [
        ("google", [], None),
        ("google", ["unknown"], None),
        ("google", ["teams"], None),
        ("microsoft", ["excel"], None),
        ("microsoft", ["outlook_calendar"], None),
        ("microsoft", ["teams"], "email@example.com"),
    ],
)
async def test_unsupported_application_operations_are_refused_before_a_credential_exchange(
    ctx, native_repo, monkeypatch, provider, products, subject
):
    from app.core.exceptions import BadRequestError

    monkeypatch.setattr(
        service_module.OrganizationSecretService, "get_usable", AsyncMock(return_value=MagicMock())
    )
    token = AsyncMock()
    monkeypatch.setattr(service_module.OrganizationSecretService, "integration_token", token)
    with pytest.raises(BadRequestError):
        await McpConnectionService(MagicMock()).connect_application_account(
            ctx,
            provider=provider,
            secret_id=SOURCE_SECRET,
            subject=subject,
            products=products,
            write=False,
            label="",
        )
    token.assert_not_awaited()
    native_repo.create_org_scoped.assert_not_awaited()


@pytest.mark.parametrize("for_organization", [False, True])
async def test_imap_connection_keeps_the_password_only_in_its_vault_envelope(
    ctx, native_repo, monkeypatch, for_organization
):
    from contextlib import asynccontextmanager

    from app.core.mail_credential import ImapCredential
    from app.services.integrations import imap

    @asynccontextmanager
    async def mailbox(credential):
        yield object()

    monkeypatch.setattr(imap, "mailbox", mailbox)
    credential = ImapCredential(
        host="imap.example.com", username="person@example.com", password="private-password"
    )
    service = McpConnectionService(MagicMock())
    row = await service.connect_imap_account(
        ctx, credential=credential, label="Mail", for_organization=for_organization
    )
    assert row.auth_type == "imap" and row.granted_scopes == ["mail:read"]
    assert "private-password" not in row.oauth_payload
    assert (
        service.integration_mail_credential(row, organization_id=ctx.organization_id) == credential
    )
    with pytest.raises(AuthorizationError):
        service.integration_mail_credential(row, organization_id=uuid4())
    row.oauth_payload = None
    with pytest.raises(AuthorizationError):
        service.integration_mail_credential(row, organization_id=ctx.organization_id)


async def test_imap_connection_does_not_attempt_login_for_a_removed_member(
    ctx, native_repo, monkeypatch
):
    from app.core.mail_credential import ImapCredential
    from app.repositories import member_repo

    monkeypatch.setattr(member_repo, "get_active", AsyncMock(return_value=None))
    with pytest.raises(AuthorizationError):
        await McpConnectionService(MagicMock()).connect_imap_account(
            ctx,
            credential=ImapCredential(
                host="imap.example.com", username="member", password="password"
            ),
            label="",
            for_organization=False,
        )
    native_repo.create.assert_not_awaited()


@pytest.mark.parametrize("provider", ["google", "microsoft", "slack"])
async def test_service_setup_is_the_same_typed_catalog_the_ui_uses(provider):
    setup = McpConnectionService(AsyncMock()).integration_setup(provider, write=True)
    assert setup.provider == provider and setup.redirect_uri.endswith(
        "/api/me/mcp-connections/oauth/callback"
    )


async def test_service_setup_refuses_an_unknown_provider():
    from app.core.exceptions import BadRequestError

    with pytest.raises(BadRequestError):
        McpConnectionService(AsyncMock()).integration_setup("unknown")


@pytest.mark.parametrize("provider", ["microsoft", "slack"])
async def test_oauth_accounts_are_named_by_the_provider_subject_after_consent(
    ctx, native_repo, monkeypatch, provider
):
    expected = "member@example.com" if provider == "microsoft" else "Client workspace / member"
    monkeypatch.setattr(
        service_module.microsoft_oauth, "account_email", AsyncMock(return_value=expected)
    )
    monkeypatch.setattr(
        service_module.slack_oauth, "identify", AsyncMock(return_value=(expected, []))
    )
    row = _account(catalog_key=provider, account_source_organization_id=ctx.organization_id)
    named = await McpConnectionService(AsyncMock())._name_account(row, "access-token")
    assert named.account_email == expected


@pytest.mark.parametrize(
    "change",
    [
        None,
        "foreign",
        "wrong_source",
        "disabled",
        "wrong_provider",
        "wrong_purpose",
        "unknown_portal",
    ],
)
async def test_native_trigger_connection_cannot_cross_owners_or_providers(ctx, native_repo, change):
    from app.core.exceptions import BadRequestError

    row = _account(
        user_id=ctx.user_id,
        scope="user",
        purpose="account",
        is_enabled=True,
        account_source_organization_id=ctx.organization_id,
    )
    portal = "google"
    if change == "foreign":
        row.user_id = uuid4()
    if change == "wrong_source":
        row.account_source_organization_id = uuid4()
    if change == "disabled":
        row.is_enabled = False
    if change == "wrong_provider":
        row.catalog_key = "slack"
    if change == "wrong_purpose":
        row.purpose = "mcp"
    if change == "unknown_portal":
        portal = "unknown"
    native_repo.get_by_id = AsyncMock(return_value=None if change is None else row)
    with pytest.raises((NotFoundError, BadRequestError)):
        await McpConnectionService(AsyncMock()).get_polled_connection(
            ctx, row.id, portal_key=portal
        )


@pytest.mark.parametrize("scope", ["user", "org", "portal"])
async def test_native_and_legacy_trigger_accounts_resolve_their_own_authority(
    ctx, native_repo, scope
):

    row = _account(
        user_id=ctx.user_id,
        scope="user",
        purpose="account",
        is_enabled=True,
        account_source_organization_id=ctx.organization_id,
    )
    service = McpConnectionService(AsyncMock())
    if scope == "portal":
        row.purpose, row.portal_key = "portal", "google"
        service.get_org_portal_connection = AsyncMock(return_value=row)
    elif scope == "org":
        row.scope, row.organization_id = "org", ctx.organization_id
        native_repo.get_account = AsyncMock(return_value=row)
    native_repo.get_by_id = AsyncMock(return_value=row)
    assert await service.get_polled_connection(ctx, row.id, portal_key="google") is row
    if scope == "portal":
        from app.core.exceptions import BadRequestError

        with pytest.raises(BadRequestError):
            await service.get_polled_connection(ctx, row.id, portal_key="microsoft")


@pytest.mark.parametrize("provider,expiry", [("slack", None), ("slack", 3600), ("microsoft", 3600)])
async def test_native_oauth_callback_keeps_browser_binding_and_actual_granted_scopes(
    repo, monkeypatch, provider, expiry
):
    from app.services.integrations.slack_oauth import SlackToken

    pending = _account(oauth_state="state", catalog_key=provider)
    pending.oauth_pending_payload = _sealed(
        pending,
        _payload(
            provider=provider, access_token=None, refresh_token=None, code_verifier="verifier"
        ),
    )
    repo.get_by_oauth_state = AsyncMock(return_value=pending)
    if provider == "slack":
        exchange = AsyncMock(
            return_value=SlackToken(
                access_token="AT",
                refresh_token="RT",
                expires_in=expiry,
                scope="channels:history,chat:write",
            )
        )
        monkeypatch.setattr(service_module.slack_oauth, "exchange_code", exchange)
    else:
        exchange = AsyncMock(
            return_value=service_module.microsoft_oauth.MicrosoftToken(
                access_token="AT", refresh_token="RT", expires_in=3600, granted_scopes=["Mail.Read"]
            )
        )
        monkeypatch.setattr(service_module.microsoft_oauth, "exchange_code", exchange)
    monkeypatch.setattr(McpConnectionService, "_name_account", AsyncMock(return_value=pending))
    await McpConnectionService(AsyncMock()).oauth_callback(
        state="state", code="code", browser_nonce=NONCE, acting_user_id=INITIATOR
    )
    assert exchange.await_count == 1
    scopes = next(
        call.kwargs["update_data"]["granted_scopes"]
        for call in repo.update.await_args_list
        if "granted_scopes" in call.kwargs["update_data"]
    )
    assert scopes == (["channels:history", "chat:write"] if provider == "slack" else ["Mail.Read"])


async def test_two_oauth_accounts_keep_their_personal_labels_and_are_selected_by_name(
    ctx, native_repo, monkeypatch
):
    from app.services.integrations import PRODUCTS, AccountSelection, IntegrationService

    monkeypatch.setattr(
        google_oauth,
        "account_email",
        AsyncMock(side_effect=["work@example.com", "personal@example.com"]),
    )
    service = McpConnectionService(AsyncMock())
    first = _account(
        user_id=ctx.user_id,
        account_source_organization_id=ctx.organization_id,
        label="Work",
        is_enabled=True,
    )
    second = _account(
        user_id=ctx.user_id,
        account_source_organization_id=ctx.organization_id,
        label="Private",
        is_enabled=True,
    )
    await service._name_account(first, "token-one")
    await service._name_account(second, "token-two")
    native_repo.list_accounts.return_value = [first, second]
    operations = IntegrationService(AsyncMock())
    assert (
        await operations.account(
            PRODUCTS["gmail"],
            AccountSelection(account_name="Work"),
            organization_id=ctx.organization_id,
            person_id=ctx.user_id,
        )
        is first
    )
    assert (
        await operations.account(
            PRODUCTS["gmail"],
            AccountSelection(account_name="Private"),
            organization_id=ctx.organization_id,
            person_id=ctx.user_id,
        )
        is second
    )


async def test_label_entered_before_consent_is_staged_on_a_reused_pending_row(
    ctx, native_repo, client
):
    pending = _account(
        user_id=ctx.user_id,
        label="Old attempt",
        account_source_organization_id=ctx.organization_id,
        is_enabled=True,
    )
    native_repo.get_pending_account.return_value = pending
    await McpConnectionService(AsyncMock()).account_start(
        ctx, for_organization=False, browser_nonce=NONCE, products=["gmail"], label="Work"
    )
    assert pending.label == "Work"


async def test_revoking_a_personal_application_credentials_grant_stops_future_token_minting(
    ctx, native_repo, monkeypatch
):
    from pydantic import SecretStr

    source = MagicMock(
        id=SOURCE_SECRET, name="Automation", authorization_generation=SOURCE_GENERATION
    )
    usable = AsyncMock(return_value=source)
    monkeypatch.setattr(service_module.OrganizationSecretService, "get_usable", usable)
    exchange = AsyncMock(return_value=SecretStr("provider-access-token"))
    monkeypatch.setattr(service_module.OrganizationSecretService, "integration_token", exchange)
    service = McpConnectionService(AsyncMock())
    row = await service.connect_application_account(
        ctx,
        provider="google",
        secret_id=SOURCE_SECRET,
        subject="person@example.com",
        products=["gmail"],
        write=False,
        label="Work",
        for_organization=False,
    )
    usable.side_effect = NotFoundError(message="Secret not found")
    exchange.reset_mock()
    assert await service.integration_access_token(row, organization_id=ctx.organization_id) is None
    exchange.assert_not_awaited()
