"""Consent lifecycle tests at repository/provider boundaries, with the real vault."""

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import SecretStr, ValidationError

from app.agents.mcp_oauth import OAuthError
from app.api.deps import get_app_connection_service, get_current_user
from app.core.config import settings
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.vault import VaultScope, seal, unseal
from app.db.models.mcp_connection import McpConnection
from app.main import app
from app.schemas.app_connection import AppConnectionCallback, AppConnectionCreate
from app.schemas.mcp_connection import (
    McpConnectionCreate,
    McpConnectionUpdate,
    OrgMcpConnectionCreate,
)
from app.services import impersonation
from app.services import mcp_connection as legacy
from app.services.app_connections import (
    APPS,
    AppConnectionService,
    ComposioAccount,
    ComposioAccountMissing,
    ComposioClient,
    composio_user_id,
    is_configured,
)
from app.services.app_connections import _service as lifecycle
from app.services.app_connections._client import (
    ComposioCatalogClient,
    ComposioCompletedAuth,
    ComposioLink,
    ComposioToolkitMetadata,
)
from app.services.mcp_catalog import CatalogAuth, get_entry

pytestmark = pytest.mark.anyio


def row(user_id, **values):
    defaults = {
        "id": uuid4(),
        "user_id": user_id,
        "organization_id": None,
        "scope": "user",
        "purpose": "mcp",
        "auth_type": "composio",
        "name": "gmail-synthetic",
        "catalog_key": "composio-gmail",
        "url": "https://backend.composio.dev/api/v3.1/toolkits/gmail",
        "auth_token": None,
        "allowed_tools": [action.name for action in APPS[0].actions],
        "secret_key_version": 1,
        "is_enabled": True,
        "is_default": False,
        "include_instructions": False,
        "label": None,
        "account_email": None,
        "composio_account_id": None,
        "composio_auth_config_id": "ac_gmail",
        "composio_status": "INITIATED",
        "oauth_state": None,
        "oauth_payload": None,
        "oauth_pending_payload": None,
        "last_status": None,
        "last_error": None,
        "last_checked_at": None,
        "last_tools": None,
        "created_at": datetime.now(UTC),
        "authorization_generation": uuid4(),
    }
    defaults.update(values)
    return McpConnection(**defaults)


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", SecretStr("synthetic-server-key"))
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", None)
    monkeypatch.setattr(
        settings, "COMPOSIO_AUTH_CONFIGS", {app.toolkit: f"ac_{app.toolkit}" for app in APPS}
    )
    monkeypatch.setattr(settings, "COMPOSIO_USER_NAMESPACE", "test-deployment")
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {1: "synthetic-master-key-" + "x" * 32})
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://t3os.example")
    db = AsyncMock()
    store = {}
    user_id = uuid4()

    async def create(_db, **values):
        owner = values.pop("user_id")
        connection = row(owner, **values)
        store[connection.id] = connection
        return connection

    async def update(_db, *, db_connection, update_data):
        for field, value in update_data.items():
            setattr(db_connection, field, value)
        return db_connection

    async def list_accounts(_db, *, user_id):
        return [
            connection
            for connection in store.values()
            if connection.user_id == user_id
            and connection.scope == "user"
            and connection.auth_type == "composio"
            and connection.purpose == "mcp"
        ]

    async def get(_db, connection_id, **kwargs):
        return store.get(connection_id)

    async def by_state(_db, state):
        return next(
            (connection for connection in store.values() if connection.oauth_state == state), None
        )

    async def delete(_db, *, db_connection):
        del store[db_connection.id]

    for name, function in {
        "create": create,
        "update": update,
        "list_composio_for_user": list_accounts,
        "get_by_id_for_update": get,
        "get_by_id": get,
        "get_by_oauth_state": by_state,
        "delete": delete,
    }.items():
        monkeypatch.setattr(lifecycle.connection_repo, name, AsyncMock(side_effect=function))
    monkeypatch.setattr(lifecycle.connection_repo, "lock_account_owner", AsyncMock())
    monkeypatch.setattr(legacy, "hold_name", AsyncMock())
    provider = AsyncMock(spec=ComposioClient)
    provider.__aenter__.return_value = provider
    provider.__aexit__.return_value = None
    sequence = 0

    async def link(**kwargs):
        nonlocal sequence
        sequence += 1
        return ComposioLink(
            connected_account_id=f"ca_attempt_{sequence}",
            redirect_url="https://connect.composio.dev/link/synthetic",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def verify(**kwargs):
        return ComposioAccount.model_validate(
            {
                "id": kwargs["account_id"],
                "toolkit": {"slug": kwargs["toolkit"]},
                "auth_config": {"id": kwargs["auth_config_id"]},
                "user_id": kwargs["user_id"],
                "status": "ACTIVE",
                "is_disabled": False,
                "state": {
                    "val": {"displayName": "Example account", "access_token": "not-for-the-browser"}
                },
            }
        )

    provider.link.side_effect = link
    provider.verify_account.side_effect = verify
    provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id="ca_attempt_1", toolkit_slug="gmail"
    )
    monkeypatch.setattr(lifecycle, "ComposioClient", lambda: provider)
    return SimpleNamespace(
        service=AppConnectionService(db), db=db, store=store, user_id=user_id, provider=provider
    )


async def start(harness, **values):
    return await harness.service.connect(
        user_id=harness.user_id, data=AppConnectionCreate(toolkit="gmail", **values)
    )


async def finish(harness, attempt, **values):
    return await harness.service.callback(
        user_id=harness.user_id,
        data=AppConnectionCallback(
            attempt_id=attempt.attempt_id,
            session_uri=SecretStr("opaque-verification-session"),
            **values,
        ),
    )


async def test_curated_catalog_is_shared_with_binding_validation(harness):
    catalog = await harness.service.catalog()
    assert catalog.configured and len(catalog.apps) == 7
    assert not catalog.catalog_available and catalog.next_cursor is None
    for catalog_app in APPS:
        assert get_entry(catalog_app.catalog_key).auth is CatalogAuth.COMPOSIO
        assert all(action.read_only for action in catalog_app.actions)
        assert len({action.name for action in catalog_app.actions}) == len(catalog_app.actions)
        entry = next(item for item in catalog.apps if item.toolkit == catalog_app.toolkit)
        assert entry.configured and entry.availability == "ready"
        assert not entry.approval_required and entry.action_count == len(catalog_app.actions)
        assert [action.side_effecting for action in entry.actions] == [
            action.side_effecting for action in catalog_app.actions
        ]
        assert [action.scopes for action in entry.actions] == [
            list(action.scopes) for action in catalog_app.actions
        ]
    serialized_actions = [
        action for app in catalog.model_dump(mode="json")["apps"] for action in app["actions"]
    ]
    assert [(action["side_effecting"], action["scopes"]) for action in serialized_actions] == [
        (action.side_effecting, list(action.scopes))
        for app in catalog.apps
        for action in app.actions
    ]
    assert "synthetic-server-key" not in catalog.model_dump_json()
    assert "ac_gmail" not in catalog.model_dump_json()


async def test_full_catalog_marks_managed_custom_and_meta_toolkits_by_policy(harness, monkeypatch):
    monkeypatch.setattr(
        settings,
        "COMPOSIO_AUTH_CONFIGS",
        {
            key: value
            for key, value in settings.COMPOSIO_AUTH_CONFIGS.items()
            if key not in {"slack", "github"}
        },
    )

    class CatalogStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def list_toolkits(self, *, search, cursor, limit):
            assert search == "CRM" and cursor == "Y3Vyc29y" and limit == 24
            return SimpleNamespace(
                items=[
                    ComposioToolkitMetadata.model_validate(
                        {
                            "slug": "salesforce",
                            "name": "Salesforce",
                            "composio_managed_auth_schemes": ["OAUTH2"],
                            "meta": {
                                "description": "Customer records.",
                                "categories": [{"id": "crm", "name": "CRM"}],
                                "tools_count": 300,
                            },
                        }
                    ),
                    ComposioToolkitMetadata.model_validate(
                        {
                            "slug": "airtable",
                            "name": "Airtable",
                            "auth_schemes": ["API_KEY"],
                            "meta": {"tools_count": 12},
                        }
                    ),
                    ComposioToolkitMetadata.model_validate(
                        {
                            "slug": "composio",
                            "name": "Composio",
                            "no_auth": True,
                            "meta": {"tools_count": 50},
                        }
                    ),
                    ComposioToolkitMetadata.model_validate(
                        {
                            "slug": "slack",
                            "name": "Slack",
                            "composio_managed_auth_schemes": ["OAUTH2"],
                            "meta": {"tools_count": 200},
                        }
                    ),
                ],
                next_cursor="bmV4dA==",
            )

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", CatalogStub)
    catalog = await harness.service.catalog(search="CRM", cursor="Y3Vyc29y", limit=24)
    assert catalog.catalog_available and catalog.next_cursor == "bmV4dA=="
    assert catalog.configured
    by_slug = {app.toolkit: app for app in catalog.apps}
    assert by_slug["salesforce"].configured
    assert by_slug["salesforce"].approval_required and by_slug["salesforce"].action_count == 300
    assert by_slug["salesforce"].actions == []
    assert by_slug["airtable"].availability == "setup_required"
    assert not by_slug["airtable"].configured
    assert by_slug["composio"].availability == "unavailable"
    assert by_slug["slack"].availability == "setup_required"


async def test_empty_successful_catalog_keeps_global_setup_state(harness, monkeypatch):
    class EmptyCatalog:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def list_toolkits(self, *, search, cursor, limit):
            assert search == "no matching app" and cursor is None and limit == 24
            return SimpleNamespace(items=[], next_cursor=None)

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", EmptyCatalog)
    catalog = await harness.service.catalog(search="no matching app")
    assert catalog.catalog_available and catalog.configured
    assert catalog.apps == [] and catalog.next_cursor is None


@pytest.mark.parametrize(
    "key,config", [(None, "ac_gmail"), (SecretStr("  "), "ac_gmail"), (SecretStr("key"), "  ")]
)
async def test_missing_operator_settings_disable_catalog_and_connect(
    harness, monkeypatch, key, config
):
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", key)
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIGS", {"gmail": config})
    assert not is_configured("gmail")
    assert not (await harness.service.catalog()).configured
    with pytest.raises(ConfigurationError):
        await start(harness)
    harness.provider.link.assert_not_awaited()


async def test_start_stores_owner_bound_attempt_not_provider_credentials(harness):
    response = await start(harness)
    connection = harness.store[response.connection_id]
    assert response.expires_at <= datetime.now(UTC) + timedelta(minutes=10)
    assert connection.user_id == harness.user_id and connection.organization_id is None
    assert connection.auth_type == "composio" and connection.is_default
    assert connection.composio_account_id is None and not connection.account_authorized
    assert connection.auth_token is None and connection.oauth_payload is None
    assert "ca_attempt_1" not in connection.oauth_pending_payload
    pending = lifecycle._pending(connection, user_id=harness.user_id)
    assert pending.account_id == "ca_attempt_1" and not pending.identity_verified
    with pytest.raises(BadRequestError):
        unseal(connection.oauth_pending_payload, scope=VaultScope.user(uuid4()))
    harness.provider.link.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        auth_config_id="ac_gmail",
        callback_url=f"https://t3os.example/connectors?connection_attempt={response.attempt_id}",
    )
    assert not (await harness.service.list_for_user(user_id=harness.user_id)).items[0].authorized


async def test_dynamic_managed_app_stores_an_exact_tool_ceiling_and_owner_bound_session(
    harness, monkeypatch
):
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", SecretStr("catalog-read-only-key"))
    metadata = ComposioToolkitMetadata.model_validate(
        {
            "slug": "salesforce",
            "name": "Salesforce",
            "composio_managed_auth_schemes": ["OAUTH2"],
            "composio_managed_auth": {"scheme": "OAUTH2", "scopes": ["read"]},
            "description": "Search your customer records.",
            "categories": [{"slug": "crm", "name": "CRM"}],
            "tools_count": 2,
        }
    )

    class CatalogStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_toolkit(self, slug):
            assert slug == "salesforce"
            return metadata

        async def direct_tool_names(self, *, toolkit):
            assert toolkit == "salesforce"
            return ["SALESFORCE_SEARCH_RECORDS", "SALESFORCE_GET_RECORD"]

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", CatalogStub)
    harness.provider.create_link_session.return_value = "trs_salesforce_1"
    harness.provider.link_session.return_value = ComposioLink(
        connected_account_id="ca_salesforce_1",
        redirect_url="https://connect.composio.dev/link/salesforce",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    attempt = await harness.service.connect(
        user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
    )
    connection = harness.store[attempt.connection_id]
    pending = lifecycle._pending(connection, user_id=harness.user_id)
    assert connection.catalog_key == "composio-salesforce"
    assert connection.url == "https://backend.composio.dev/api/v3.1/toolkits/salesforce"
    assert connection.allowed_tools == ["SALESFORCE_SEARCH_RECORDS", "SALESFORCE_GET_RECORD"]
    assert connection.composio_auth_config_id is None
    assert pending.dynamic and pending.session_id == "trs_salesforce_1"
    assert pending.auth_config_id is None
    assert pending.session_id not in (connection.oauth_pending_payload or "")
    harness.provider.create_link_session.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        toolkit="salesforce",
        tools=connection.allowed_tools,
    )
    harness.provider.link_session.assert_awaited_once_with(
        session_id="trs_salesforce_1", toolkit="salesforce"
    )

    harness.provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id="ca_salesforce_1", toolkit_slug="salesforce"
    )
    harness.provider.discover_account_auth_config.return_value = ComposioAccount.model_validate(
        {
            "id": "ca_salesforce_1",
            "toolkit": {"slug": "salesforce"},
            "auth_config": {"id": "ac_salesforce_managed"},
            "user_id": composio_user_id(harness.user_id),
            "status": "ACTIVE",
            "is_disabled": False,
        }
    )
    result = await finish(harness, attempt, connected_account_id="ca_salesforce_1")
    assert result.authorized and result.status == "connected"
    assert result.app.configured and result.app.approval_required
    assert result.app.action_count == 2
    assert connection.composio_auth_config_id == "ac_salesforce_managed"
    assert connection.composio_account_id == "ca_salesforce_1"
    assert connection.oauth_pending_payload is None and connection.oauth_state is None
    harness.provider.discover_account_auth_config.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        toolkit="salesforce",
        account_id="ca_salesforce_1",
    )
    harness.provider.verify_account.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        toolkit="salesforce",
        account_id="ca_salesforce_1",
        auth_config_id="ac_salesforce_managed",
    )
    assert "trs_salesforce_1" not in result.model_dump_json()


async def test_dynamic_app_can_use_explicit_operator_auth_without_managed_auth(
    harness, monkeypatch
):
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", SecretStr("catalog-read-only-key"))
    monkeypatch.setattr(
        settings,
        "COMPOSIO_AUTH_CONFIGS",
        {**settings.COMPOSIO_AUTH_CONFIGS, "salesforce": "ac_salesforce_operator"},
    )
    metadata = ComposioToolkitMetadata.model_validate(
        {
            "slug": "salesforce",
            "name": "Salesforce",
            "auth_schemes": ["API_KEY"],
            "tools_count": 1,
        }
    )

    class CatalogStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_toolkit(self, slug):
            assert slug == "salesforce"
            return metadata

        async def direct_tool_names(self, *, toolkit):
            assert toolkit == "salesforce"
            return ["SALESFORCE_SEARCH_RECORDS"]

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", CatalogStub)
    attempt = await harness.service.connect(
        user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
    )
    connection = harness.store[attempt.connection_id]
    assert connection.allowed_tools == ["SALESFORCE_SEARCH_RECORDS"]
    assert connection.composio_auth_config_id == "ac_salesforce_operator"
    harness.provider.link.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        auth_config_id="ac_salesforce_operator",
        callback_url=f"https://t3os.example/connectors?connection_attempt={attempt.attempt_id}",
    )
    harness.provider.create_link_session.assert_not_awaited()

    harness.provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id="ca_attempt_1", toolkit_slug="salesforce"
    )
    connected = await finish(harness, attempt, connected_account_id="ca_attempt_1")
    assert connected.authorized and connected.app.approval_required
    assert connected.app.action_count == 1
    harness.provider.verify_account.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        toolkit="salesforce",
        account_id="ca_attempt_1",
        auth_config_id="ac_salesforce_operator",
    )

    reconnect = await harness.service.reconnect(
        user_id=harness.user_id, connection_id=connection.id
    )
    assert reconnect.attempt_id != attempt.attempt_id
    assert harness.provider.link.await_count == 2
    harness.provider.link.assert_awaited_with(
        user_id=composio_user_id(harness.user_id),
        auth_config_id="ac_salesforce_operator",
        callback_url=f"https://t3os.example/connectors?connection_attempt={reconnect.attempt_id}",
    )
    assert connection.composio_account_id == "ca_attempt_1" and connection.account_authorized


async def test_dynamic_account_list_uses_saved_descriptor_without_catalog_requests(
    harness, monkeypatch
):
    connection = row(
        harness.user_id,
        catalog_key="composio-salesforce",
        url="https://backend.composio.dev/api/v3.1/toolkits/salesforce",
        allowed_tools=["SALESFORCE_SEARCH_RECORDS"],
        composio_auth_config_id="ac_salesforce_managed",
    )
    harness.store[connection.id] = connection

    class CatalogMustNotBeRead:
        def __init__(self):
            raise AssertionError("account listing must not depend on catalog availability")

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", CatalogMustNotBeRead)
    result = await harness.service.list_for_user(user_id=harness.user_id)
    assert result.total == 1
    assert result.items[0].app.toolkit == "salesforce"
    assert result.items[0].app.configured and result.items[0].app.approval_required
    assert result.items[0].app.action_count == 1


async def test_multiple_accounts_have_separate_attempts_and_default(harness):
    first = await start(harness, label="Work")
    second = await start(harness)
    assert first.connection_id != second.connection_id
    assert harness.store[first.connection_id].label == "Work"
    assert harness.store[second.connection_id].label == "Account 2"
    assert not harness.store[second.connection_id].is_default
    assert (await harness.service.list_for_user(user_id=uuid4())).total == 0


async def test_success_requires_signed_identity_then_exact_active_account(harness):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    old_generation = connection.authorization_generation
    result = await finish(harness, attempt, connected_account_id="ca_attempt_1")
    assert result.status == "connected" and result.authorized
    assert result.readiness == "authorization_verified" and result.identity == "Example account"
    assert connection.oauth_state is None and connection.oauth_pending_payload is None
    assert connection.composio_account_id == "ca_attempt_1"
    assert connection.authorization_generation != old_generation
    assert "not-for-the-browser" not in result.model_dump_json()
    assert "ca_attempt_1" not in result.model_dump_json()
    harness.provider.verify_account.assert_awaited_once_with(
        user_id=composio_user_id(harness.user_id),
        toolkit="gmail",
        account_id="ca_attempt_1",
        auth_config_id="ac_gmail",
    )


async def test_static_verifier_callback_can_resolve_session_uri_without_attempt_id(harness):
    await start(harness)
    result = await harness.service.callback(
        user_id=harness.user_id, data=AppConnectionCallback(session_uri=SecretStr("opaque"))
    )
    assert result.authorized


async def test_browser_callback_strings_alone_cannot_enable_account(harness):
    attempt = await start(harness)
    with pytest.raises(BadRequestError, match="identity verification"):
        await harness.service.callback(
            user_id=harness.user_id,
            data=AppConnectionCallback(
                attempt_id=attempt.attempt_id, connected_account_id="ca_attempt_1"
            ),
        )
    result = await harness.service.refresh(
        user_id=harness.user_id, connection_id=attempt.connection_id
    )
    assert not result.authorized and result.status == "pending"
    harness.provider.verify_account.assert_not_awaited()


async def test_unverified_pending_grant_cannot_be_promoted_by_completion_helper(harness):
    attempt = await start(harness)
    result = await harness.service._finish(
        harness.store[attempt.connection_id], user_id=harness.user_id, client=harness.provider
    )
    assert not result.authorized
    harness.provider.verify_account.assert_not_awaited()


async def test_wrong_owner_cannot_consume_attempt_or_contact_provider(harness):
    attempt = await start(harness)
    with pytest.raises(NotFoundError):
        await harness.service.callback(
            user_id=uuid4(),
            data=AppConnectionCallback(
                attempt_id=attempt.attempt_id, session_uri=SecretStr("opaque")
            ),
        )
    harness.provider.complete_auth.assert_not_awaited()
    assert not harness.store[attempt.connection_id].account_authorized


@pytest.mark.parametrize("method", ["refresh", "reconnect", "delete"])
async def test_lifecycle_actions_reject_foreign_owner(harness, method):
    attempt = await start(harness)
    with pytest.raises(NotFoundError):
        await getattr(harness.service, method)(user_id=uuid4(), connection_id=attempt.connection_id)


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "org", "organization_id": uuid4()},
        {"purpose": "account"},
        {"auth_type": "oauth"},
        {"organization_id": uuid4()},
    ],
)
async def test_managed_api_cannot_adopt_another_connection_kind(harness, changes):
    connection = row(harness.user_id, **changes)
    harness.store[connection.id] = connection
    with pytest.raises(NotFoundError):
        await harness.service.refresh(user_id=harness.user_id, connection_id=connection.id)


async def test_callback_account_hint_mismatch_rejected_before_verification(harness):
    attempt = await start(harness)
    with pytest.raises(BadRequestError, match="did not match"):
        await finish(harness, attempt, connected_account_id="ca_someone_else")
    harness.provider.complete_auth.assert_not_awaited()


@pytest.mark.parametrize(
    "account_id,toolkit", [("ca_someone_else", "gmail"), ("ca_attempt_1", "slack")]
)
async def test_identity_result_must_match_saved_attempt(harness, account_id, toolkit):
    attempt = await start(harness)
    harness.provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id=account_id, toolkit_slug=toolkit
    )
    with pytest.raises(BadRequestError, match="did not match"):
        await finish(harness, attempt)
    harness.provider.verify_account.assert_not_awaited()
    assert not harness.store[attempt.connection_id].account_authorized


async def test_expired_or_replayed_attempt_cannot_enable_account(harness):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    pending = lifecycle._pending(connection, user_id=harness.user_id)
    pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection.oauth_pending_payload = lifecycle._sealed_pending(connection, pending)
    with pytest.raises(BadRequestError, match="expired"):
        await finish(harness, attempt)
    assert (await harness.service.list_for_user(user_id=harness.user_id)).items[
        0
    ].status == "expired"
    harness.provider.complete_auth.assert_not_awaited()
    pending.expires_at = datetime.now(UTC) + timedelta(minutes=1)
    connection.oauth_pending_payload = lifecycle._sealed_pending(connection, pending)
    await finish(harness, attempt)
    with pytest.raises(NotFoundError):
        await finish(harness, attempt)


async def test_reconnect_preserves_old_grant_until_new_verified_account_is_ready(
    harness, monkeypatch
):
    first = await start(harness, label="My work account")
    await finish(harness, first)
    connection = harness.store[first.connection_id]
    generation = connection.authorization_generation
    monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIGS", {"gmail": "ac_new_config"})
    second = await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)
    assert connection.composio_account_id == "ca_attempt_1" and connection.account_authorized
    assert (
        connection.composio_auth_config_id == "ac_gmail"
        and connection.authorization_generation == generation
    )
    assert connection.label == "My work account"
    harness.provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id="ca_attempt_2", toolkit_slug="gmail"
    )
    await finish(harness, second)
    assert (
        connection.composio_account_id == "ca_attempt_2"
        and connection.composio_auth_config_id == "ac_new_config"
    )
    assert connection.authorization_generation != generation
    harness.provider.delete_account.assert_awaited_once_with("ca_attempt_1")


async def test_restarting_pending_consent_cleans_up_superseded_provider_account(harness):
    first = await start(harness)
    second = await harness.service.reconnect(
        user_id=harness.user_id, connection_id=first.connection_id
    )
    harness.provider.delete_account.assert_awaited_once_with("ca_attempt_1")
    with pytest.raises(NotFoundError):
        await finish(harness, first)
    assert second.attempt_id != first.attempt_id


async def test_single_use_identity_verification_survives_provider_metadata_outage(harness):
    attempt = await start(harness)
    verifier = harness.provider.verify_account.side_effect
    harness.provider.verify_account.side_effect = ExternalServiceError(
        message="raw-provider-secret"
    )
    result = await finish(harness, attempt)
    assert not result.authorized and result.readiness == "unavailable"
    assert "raw-provider-secret" not in result.model_dump_json()
    assert lifecycle._pending(
        harness.store[attempt.connection_id], user_id=harness.user_id
    ).identity_verified
    harness.provider.verify_account.side_effect = verifier
    result = await harness.service.refresh(
        user_id=harness.user_id, connection_id=attempt.connection_id
    )
    assert result.authorized
    harness.provider.complete_auth.assert_awaited_once()


@pytest.mark.parametrize(
    "status,disabled,config_disabled",
    [
        ("INITIATED", False, False),
        ("FAILED", False, False),
        ("EXPIRED", False, False),
        ("ACTIVE", True, False),
        ("ACTIVE", False, True),
    ],
)
async def test_inactive_or_disabled_provider_grants_never_activate(
    harness, status, disabled, config_disabled
):
    attempt = await start(harness)
    harness.provider.verify_account.side_effect = None
    harness.provider.verify_account.return_value = ComposioAccount.model_validate(
        {
            "id": "ca_attempt_1",
            "toolkit": {"slug": "gmail"},
            "auth_config": {"id": "ac_gmail", "is_disabled": config_disabled},
            "status": status,
            "is_disabled": disabled,
        }
    )
    result = await finish(harness, attempt)
    assert not result.authorized


async def test_disconnect_removes_active_and_pending_provider_accounts(harness):
    attempt = await start(harness)
    await finish(harness, attempt)
    await harness.service.reconnect(user_id=harness.user_id, connection_id=attempt.connection_id)
    await harness.service.delete(user_id=harness.user_id, connection_id=attempt.connection_id)
    assert {call.args[0] for call in harness.provider.delete_account.await_args_list} == {
        "ca_attempt_1",
        "ca_attempt_2",
    }
    assert attempt.connection_id not in harness.store


async def test_provider_disconnect_failure_keeps_local_binding_reviewable(harness):
    attempt = await start(harness)
    harness.provider.delete_account.side_effect = ExternalServiceError()
    with pytest.raises(ExternalServiceError):
        await harness.service.delete(user_id=harness.user_id, connection_id=attempt.connection_id)
    assert attempt.connection_id in harness.store


@pytest.mark.parametrize(
    "error,expected_status",
    [(ComposioAccountMissing(), "expired"), (ExternalServiceError(message="secret"), "connected")],
)
async def test_refresh_distinguishes_revoked_grant_from_transient_outage(
    harness, error, expected_status
):
    attempt = await start(harness)
    await finish(harness, attempt)
    harness.provider.verify_account.side_effect = error
    result = await harness.service.refresh(
        user_id=harness.user_id, connection_id=attempt.connection_id
    )
    assert result.status == expected_status and result.readiness == "unavailable"
    assert "secret" not in result.last_error
    assert result.authorized == (expected_status == "connected")


async def test_impersonation_cannot_bind_administrators_account_to_member(harness):
    token = impersonation._active.set(
        impersonation.ActiveImpersonation(
            session_id=uuid4(),
            user_id=harness.user_id,
            impersonator_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    try:
        with pytest.raises(AuthorizationError):
            await start(harness)
    finally:
        impersonation._active.reset(token)
    harness.provider.link.assert_not_awaited()


@pytest.mark.parametrize(
    "values",
    [
        {"url": "https://evil.example/mcp"},
        {"auth_token": "arbitrary"},
        {"clear_allowed_tools": True},
        {"allowed_tools": ["GMAIL_SEND_EMAIL"]},
        {"include_instructions": True},
    ],
)
async def test_legacy_patch_cannot_replace_managed_credentials_or_expand_actions(harness, values):
    attempt = await start(harness)
    with pytest.raises(BadRequestError, match="allowed actions"):
        await legacy.McpConnectionService(harness.db).update(
            user_id=harness.user_id,
            connection_id=attempt.connection_id,
            data=McpConnectionUpdate(**values),
        )


async def test_legacy_patch_keeps_labels_enable_and_narrowed_action_controls(harness):
    attempt = await start(harness)
    connection = await legacy.McpConnectionService(harness.db).update(
        user_id=harness.user_id,
        connection_id=attempt.connection_id,
        data=McpConnectionUpdate(
            label="Personal", is_enabled=False, allowed_tools=["GMAIL_FETCH_EMAILS"]
        ),
    )
    assert connection.label == "Personal" and not connection.is_enabled
    assert connection.allowed_tools == ["GMAIL_FETCH_EMAILS"]


async def test_a_managed_app_label_change_preserves_the_authorization_generation(harness):
    connection = row(harness.user_id, composio_status="ACTIVE", composio_account_id="ca_existing")
    harness.store[connection.id] = connection
    generation = connection.authorization_generation
    allowed_tools = list(connection.allowed_tools)

    updated = await legacy.McpConnectionService(harness.db).update(
        user_id=harness.user_id,
        connection_id=connection.id,
        data=McpConnectionUpdate(label="Personal calendar"),
    )

    assert updated.label == "Personal calendar"
    assert updated.authorization_generation == generation
    assert updated.allowed_tools == allowed_tools
    assert updated.is_enabled
    assert not harness.provider.mock_calls


@pytest.mark.parametrize("method", ["delete", "test"])
async def test_legacy_delete_and_probe_use_managed_lifecycle(harness, method):
    attempt = await start(harness)
    with pytest.raises(BadRequestError, match="Apps"):
        await getattr(legacy.McpConnectionService(harness.db), method)(
            user_id=harness.user_id, connection_id=attempt.connection_id
        )
    assert attempt.connection_id in harness.store


async def test_legacy_create_oauth_and_callback_cannot_forge_managed_binding(harness):
    service = legacy.McpConnectionService(harness.db)
    with pytest.raises(BadRequestError, match="Apps"):
        await service.create(
            user_id=harness.user_id,
            data=McpConnectionCreate(
                name="forged", catalog_key="composio-gmail", url="https://evil.example/mcp"
            ),
        )
    with pytest.raises(BadRequestError, match="Apps"):
        await service.oauth_start(
            user_id=harness.user_id,
            name="forged",
            catalog_key="composio-gmail",
            url="https://evil.example/mcp",
        )
    attempt = await start(harness)
    with pytest.raises(OAuthError, match="Apps"):
        await service.oauth_callback(state=str(attempt.attempt_id), code="untrusted")


def test_callback_requires_attempt_or_identity_session():
    with pytest.raises(ValidationError):
        AppConnectionCallback(connected_account_id="ca_untrusted")


async def test_unrelated_corrupt_attempt_does_not_block_static_verifier_callback(harness):
    corrupt = row(
        harness.user_id, oauth_state=str(uuid4()), oauth_pending_payload="corrupt-envelope"
    )
    harness.store[corrupt.id] = corrupt
    await start(harness)
    result = await harness.service.callback(
        user_id=harness.user_id, data=AppConnectionCallback(session_uri=SecretStr("opaque"))
    )
    assert result.authorized
    listing = await harness.service.list_for_user(user_id=harness.user_id)
    assert listing.items[0].status == "failed"


async def test_refresh_cannot_promote_pending_grant_while_impersonating(harness):
    attempt = await start(harness)
    harness.provider.verify_account.side_effect = ExternalServiceError()
    await finish(harness, attempt)
    token = impersonation._active.set(
        impersonation.ActiveImpersonation(
            session_id=uuid4(),
            user_id=harness.user_id,
            impersonator_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    try:
        with pytest.raises(AuthorizationError):
            await harness.service.refresh(
                user_id=harness.user_id, connection_id=attempt.connection_id
            )
    finally:
        impersonation._active.reset(token)
    assert not harness.store[attempt.connection_id].account_authorized


async def test_catalog_rejects_unknown_toolkit_and_limits_abandoned_rows(harness, monkeypatch):
    with pytest.raises(ConfigurationError, match="COMPOSIO_CATALOG_API_KEY"):
        await harness.service.connect(
            user_id=harness.user_id, data=AppConnectionCreate(toolkit="unreviewed")
        )
    monkeypatch.setattr(lifecycle, "_MAX_ACCOUNTS", 1)
    await start(harness)
    with pytest.raises(BadRequestError, match="Remove an unused"):
        await start(harness)


async def test_expired_link_is_not_sent_to_browser(harness):
    harness.provider.link.side_effect = None
    harness.provider.link.return_value = ComposioLink(
        connected_account_id="ca_expired",
        redirect_url="https://connect.composio.dev/link/synthetic",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    with pytest.raises(ExternalServiceError, match="expired"):
        await start(harness)


async def test_dynamic_expired_link_is_not_sent_to_browser(harness, monkeypatch):
    monkeypatch.setattr(settings, "COMPOSIO_CATALOG_API_KEY", SecretStr("catalog-read-only-key"))
    metadata = ComposioToolkitMetadata.model_validate(
        {
            "slug": "salesforce",
            "name": "Salesforce",
            "composio_managed_auth_schemes": ["OAUTH2"],
            "composio_managed_auth": {"scheme": "OAUTH2", "scopes": ["read"]},
            "description": "Search your customer records.",
            "categories": [{"slug": "crm", "name": "CRM"}],
            "tools_count": 2,
        }
    )

    class CatalogStub:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_toolkit(self, slug):
            assert slug == "salesforce"
            return metadata

        async def direct_tool_names(self, *, toolkit):
            assert toolkit == "salesforce"
            return ["SALESFORCE_SEARCH_RECORDS", "SALESFORCE_GET_RECORD"]

    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", CatalogStub)
    harness.provider.create_link_session.return_value = "trs_salesforce_expired"
    harness.provider.link_session.return_value = ComposioLink(
        connected_account_id="ca_salesforce_expired",
        redirect_url="https://connect.composio.dev/link/salesforce",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with pytest.raises(ExternalServiceError, match="expired"):
        await harness.service.connect(
            user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
        )

    assert not any(connection.oauth_state for connection in harness.store.values())


async def test_reconnect_cleanup_failure_retains_old_grant_and_verified_pending(harness):
    first = await start(harness)
    await finish(harness, first)
    second = await harness.service.reconnect(
        user_id=harness.user_id, connection_id=first.connection_id
    )
    harness.provider.complete_auth.return_value = ComposioCompletedAuth(
        connected_account_id="ca_attempt_2", toolkit_slug="gmail"
    )
    harness.provider.delete_account.side_effect = ExternalServiceError(
        message="private-provider-error"
    )
    result = await finish(harness, second)
    connection = harness.store[first.connection_id]
    assert connection.composio_account_id == "ca_attempt_1" and connection.account_authorized
    assert (
        result.readiness == "unavailable"
        and "private-provider-error" not in result.model_dump_json()
    )
    assert lifecycle._pending(connection, user_id=harness.user_id).identity_verified
    harness.provider.delete_account.side_effect = None
    result = await harness.service.refresh(user_id=harness.user_id, connection_id=connection.id)
    assert result.authorized and connection.composio_account_id == "ca_attempt_2"


async def test_refresh_records_healthy_and_disabled_provider_status(harness):
    attempt = await start(harness)
    await finish(harness, attempt)
    result = await harness.service.refresh(
        user_id=harness.user_id, connection_id=attempt.connection_id
    )
    assert result.readiness == "authorization_verified"
    verifier = harness.provider.verify_account.side_effect
    account = await verifier(
        user_id=composio_user_id(harness.user_id),
        toolkit="gmail",
        account_id="ca_attempt_1",
        auth_config_id="ac_gmail",
    )
    account.is_disabled = True
    harness.provider.verify_account.side_effect = None
    harness.provider.verify_account.return_value = account
    result = await harness.service.refresh(
        user_id=harness.user_id, connection_id=attempt.connection_id
    )
    assert result.status == "disabled" and not result.authorized


async def test_org_mcp_routes_cannot_create_managed_personal_binding(harness):
    service = legacy.McpConnectionService(harness.db)
    context = SimpleNamespace(organization_id=uuid4(), subject_id=harness.user_id)
    with pytest.raises(BadRequestError, match="Apps"):
        await service.create_for_org(
            context,
            OrgMcpConnectionCreate(
                name="forged", catalog_key="composio-gmail", url="https://evil.example/mcp"
            ),
        )
    with pytest.raises(BadRequestError, match="Apps"):
        await service.oauth_start_for_org(
            context, name="forged", catalog_key="composio-gmail", url="https://evil.example/mcp"
        )


async def test_legacy_oauth_cannot_reuse_managed_name_without_catalog_key(harness, monkeypatch):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    monkeypatch.setattr(
        lifecycle.connection_repo, "get_by_name", AsyncMock(return_value=connection)
    )
    with pytest.raises(BadRequestError, match="Apps"):
        await legacy.McpConnectionService(harness.db).oauth_start(
            user_id=harness.user_id, name=connection.name, url="https://evil.example/mcp"
        )


async def test_api_contract_uses_authenticated_member_and_safe_metadata(harness, client):
    app.dependency_overrides[get_app_connection_service] = lambda: harness.service
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=harness.user_id)
    catalog = await client.get("/api/v1/me/app-connections/catalog")
    assert catalog.status_code == 200 and len(catalog.json()["apps"]) == 7
    response = await client.post(
        "/api/v1/me/app-connections/connect", json={"toolkit": "gmail", "user_id": str(uuid4())}
    )
    assert response.status_code == 201
    started = response.json()
    assert set(started) == {"connection_id", "attempt_id", "redirect_url", "expires_at"}
    callback = await client.post(
        "/api/v1/me/app-connections/callback",
        json={"attempt_id": started["attempt_id"], "session_uri": "opaque", "status": "failed"},
    )
    assert callback.status_code == 200 and callback.json()["authorized"]
    assert callback.json()["readiness"] == "authorization_verified"
    assert "synthetic-server-key" not in callback.text and "ca_attempt_1" not in callback.text
    listing = await client.get("/api/v1/me/app-connections")
    assert listing.status_code == 200 and listing.json()["total"] == 1
    refresh = await client.post(
        f"/api/v1/me/app-connections/{started['connection_id']}/refresh", json={}
    )
    assert refresh.status_code == 200 and refresh.json()["authorized"]
    reconnect = await client.post(
        f"/api/v1/me/app-connections/{started['connection_id']}/reconnect", json={}
    )
    assert reconnect.status_code == 200
    disconnect = await client.delete(f"/api/v1/me/app-connections/{started['connection_id']}")
    assert disconnect.status_code == 204


@pytest.mark.parametrize(
    "path,method", [("/catalog", "get"), ("", "get"), ("/callback", "post"), ("/connect", "post")]
)
async def test_app_routes_require_signed_in_session(harness, client, path, method):
    app.dependency_overrides[get_app_connection_service] = lambda: harness.service
    response = await getattr(client, method)(f"/api/v1/me/app-connections{path}")
    assert response.status_code == 401
    harness.provider.complete_auth.assert_not_awaited()
    harness.provider.link.assert_not_awaited()


def test_rollback_disables_managed_rows_before_dropping_metadata_without_deleting_accounts(
    monkeypatch,
):
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0298_composio_connections.py"
    )
    spec = spec_from_file_location("composio_migration_test", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    monkeypatch.setattr(migration, "op", Operations(context))
    migration.upgrade()
    upgrade_sql = output.getvalue()
    assert "ADD COLUMN composio_account_id VARCHAR(128)" in upgrade_sql
    assert "ADD COLUMN composio_auth_config_id VARCHAR(128)" in upgrade_sql
    assert "ADD COLUMN composio_status VARCHAR(32)" in upgrade_sql
    assert "UPDATE" not in upgrade_sql and "DELETE" not in upgrade_sql
    output.seek(0)
    output.truncate()
    migration.downgrade()
    downgrade_sql = output.getvalue()
    assert downgrade_sql.index(
        "SET is_enabled = false WHERE auth_type = 'composio'"
    ) < downgrade_sql.index("DROP COLUMN")
    assert "DELETE" not in downgrade_sql


async def test_retired_managed_catalog_entry_cannot_be_used(harness):
    connection = row(harness.user_id, catalog_key="composio-unreviewed")
    harness.store[connection.id] = connection
    with pytest.raises(BadRequestError, match="supported catalog"):
        await harness.service.refresh(user_id=harness.user_id, connection_id=connection.id)
    harness.provider.verify_account.assert_not_awaited()


async def test_pending_envelope_requires_matching_state(harness):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    connection.oauth_state = None
    with pytest.raises(BadRequestError, match="no longer available"):
        await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)


@pytest.mark.parametrize("change", ["owner", "attempt", "toolkit", "timezone"])
async def test_even_validly_sealed_pending_metadata_must_match_its_record(harness, change):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    pending = lifecycle._pending(connection, user_id=harness.user_id)
    if change == "owner":
        pending.user_id = uuid4()
    elif change == "attempt":
        pending.attempt_id = uuid4()
    elif change == "toolkit":
        pending.toolkit = "slack"
    else:
        pending.expires_at = pending.expires_at.replace(tzinfo=None)
    connection.oauth_pending_payload = seal(
        pending.model_dump_json(), scope=VaultScope.user(harness.user_id), key_version=1
    ).ciphertext
    with pytest.raises(BadRequestError, match="did not match"):
        await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)


async def test_restarting_consent_never_deletes_same_id_as_current_working_account(harness):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    connection.composio_account_id = "ca_attempt_1"
    connection.composio_status = "ACTIVE"
    await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)
    assert connection.account_authorized and connection.composio_account_id == "ca_attempt_1"
    harness.provider.delete_account.assert_not_awaited()


async def test_static_callback_with_only_expired_and_completed_accounts_does_not_consume_session(
    harness,
):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    pending = lifecycle._pending(connection, user_id=harness.user_id)
    pending.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    connection.oauth_pending_payload = lifecycle._sealed_pending(connection, pending)
    completed = row(harness.user_id, composio_account_id="ca_older", composio_status="ACTIVE")
    harness.store[completed.id] = completed
    with pytest.raises(BadRequestError, match="No live connection"):
        await harness.service.callback(
            user_id=harness.user_id, data=AppConnectionCallback(session_uri=SecretStr("opaque"))
        )
    harness.provider.complete_auth.assert_not_awaited()


async def test_callback_rechecks_saved_attempt_after_identity_provider_returns(harness):
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]

    async def replaced(**kwargs):
        pending = lifecycle._pending(connection, user_id=harness.user_id)
        pending.attempt_id = uuid4()
        connection.oauth_state = str(pending.attempt_id)
        connection.oauth_pending_payload = lifecycle._sealed_pending(connection, pending)
        return ComposioCompletedAuth(connected_account_id="ca_attempt_1", toolkit_slug="gmail")

    harness.provider.complete_auth.side_effect = replaced
    with pytest.raises(BadRequestError, match="replaced"):
        await finish(harness, attempt)
    harness.provider.verify_account.assert_not_awaited()


async def test_static_callback_rejects_mismatched_browser_account_hint(harness):
    await start(harness)
    with pytest.raises(BadRequestError, match="did not match"):
        await harness.service.callback(
            user_id=harness.user_id,
            data=AppConnectionCallback(
                session_uri=SecretStr("opaque"), connected_account_id="ca_browser_guess"
            ),
        )
    harness.provider.verify_account.assert_not_awaited()


async def test_disconnect_of_completed_account_has_no_pending_grant_to_remove(harness):
    attempt = await start(harness)
    await finish(harness, attempt)
    await harness.service.delete(user_id=harness.user_id, connection_id=attempt.connection_id)
    harness.provider.delete_account.assert_awaited_once_with("ca_attempt_1")


async def test_empty_local_record_can_be_removed_without_provider_key(harness, monkeypatch):
    connection = row(harness.user_id)
    harness.store[connection.id] = connection
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", None)
    assert (await harness.service.list_for_user(user_id=harness.user_id)).items[
        0
    ].readiness == "unavailable"
    await harness.service.delete(user_id=harness.user_id, connection_id=connection.id)
    assert not harness.store
    harness.provider.delete_account.assert_not_awaited()


@pytest.mark.parametrize("path", ["personal_catalog", "personal_name", "org_catalog"])
async def test_managed_google_request_refused_before_org_app_lookup(harness, monkeypatch, path):
    """The Google convenience flow cannot retarget a managed Composio account."""
    attempt = await start(harness)
    connection = harness.store[attempt.connection_id]
    monkeypatch.setattr(
        lifecycle.connection_repo, "get_by_name", AsyncMock(return_value=connection)
    )
    org_app = AsyncMock(return_value=(SimpleNamespace(client_id="org-google-client"), None, None))
    monkeypatch.setattr(legacy.OrganizationSecretService, "oauth_app_identity", org_app)
    context = SimpleNamespace(
        organization_id=uuid4(), user_id=harness.user_id, subject_id=harness.user_id
    )
    service = legacy.McpConnectionService(harness.db)
    google_url = "https://calendarmcp.googleapis.com/mcp/v1"
    with pytest.raises(BadRequestError, match="Apps"):
        if path == "org_catalog":
            await service.oauth_start_for_org(
                context, name=connection.name, url=google_url, catalog_key=connection.catalog_key
            )
        else:
            await service.oauth_start(
                user_id=harness.user_id,
                name=connection.name,
                url=google_url,
                ctx=context,
                catalog_key=connection.catalog_key if path == "personal_catalog" else None,
            )
    org_app.assert_not_awaited()
    assert connection.auth_type == "composio" and connection.oauth_payload is None


def dynamic_catalog(monkeypatch, *, metadata=None, next_cursor=None):
    """A provider boundary with real parsed metadata and no network."""
    metadata = metadata or ComposioToolkitMetadata(
        slug="salesforce",
        name="Salesforce",
        composio_managed_auth_schemes=["OAUTH2"],
        tools_count=1,
    )
    catalog = AsyncMock(spec=ComposioCatalogClient)
    catalog.__aenter__.return_value = catalog
    catalog.__aexit__.return_value = None
    catalog.list_toolkits.return_value = SimpleNamespace(items=[metadata], next_cursor=next_cursor)
    catalog.get_toolkit.return_value = metadata
    catalog.direct_tool_names.return_value = ["SALESFORCE_SEARCH_RECORDS"]
    monkeypatch.setattr(lifecycle, "ComposioCatalogClient", lambda: catalog)
    return catalog


@pytest.mark.security
@pytest.mark.parametrize("cursor", ["invalid cursor", "a" * 513])
async def test_catalog_refuses_invalid_caller_cursor_before_provider_io(
    harness, monkeypatch, cursor
):
    catalog = dynamic_catalog(monkeypatch)
    with pytest.raises(BadRequestError, match="cursor"):
        await harness.service.catalog(cursor=cursor)
    catalog.list_toolkits.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("cursor", ["invalid cursor", "a" * 513])
async def test_catalog_refuses_invalid_provider_cursor(harness, monkeypatch, cursor):
    catalog = dynamic_catalog(monkeypatch, next_cursor=cursor)
    with pytest.raises(ExternalServiceError, match="catalog cursor"):
        await harness.service.catalog()
    catalog.list_toolkits.assert_awaited_once()


@pytest.mark.security
async def test_catalog_drops_a_toolkit_whose_slug_cannot_be_a_saved_binding(harness, monkeypatch):
    catalog = dynamic_catalog(monkeypatch)
    catalog.list_toolkits.return_value.items.insert(
        0, ComposioToolkitMetadata(slug="../foreign", name="Foreign")
    )
    result = await harness.service.catalog()
    assert [entry.toolkit for entry in result.apps] == ["salesforce"]


@pytest.mark.parametrize(
    ("runtime_key", "tools_count", "availability"),
    [(None, 1, "unavailable"), (SecretStr("synthetic-runtime"), 1001, "setup_required")],
)
async def test_dynamic_catalog_requires_runtime_and_a_bounded_action_set(
    harness, monkeypatch, runtime_key, tools_count, availability
):
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", runtime_key)
    dynamic_catalog(
        monkeypatch,
        metadata=ComposioToolkitMetadata(
            slug="salesforce",
            name="Salesforce",
            tools_count=tools_count,
            composio_managed_auth_schemes=["OAUTH2"],
        ),
    )
    entry = (await harness.service.catalog()).apps[0]
    assert entry.availability == availability and not entry.configured


@pytest.mark.security
async def test_dynamic_connect_requires_runtime_before_any_provider_or_repository_write(
    harness, monkeypatch
):
    catalog = dynamic_catalog(monkeypatch)
    monkeypatch.setattr(settings, "COMPOSIO_API_KEY", None)
    with pytest.raises(ConfigurationError, match="COMPOSIO_API_KEY"):
        await harness.service.connect(
            user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
        )
    catalog.get_toolkit.assert_not_awaited()
    harness.provider.create_link_session.assert_not_awaited()
    assert not harness.store


@pytest.mark.security
@pytest.mark.parametrize(
    "metadata",
    [
        ComposioToolkitMetadata(
            slug="foreign", name="Foreign", composio_managed_auth_schemes=["OAUTH2"]
        ),
        ComposioToolkitMetadata(slug="salesforce", name="Salesforce", no_auth=True),
        ComposioToolkitMetadata(
            slug="salesforce",
            name="Salesforce",
            tools_count=1001,
            composio_managed_auth_schemes=["OAUTH2"],
        ),
    ],
)
async def test_dynamic_connect_cannot_adopt_a_different_or_unavailable_toolkit(
    harness, monkeypatch, metadata
):
    catalog = dynamic_catalog(monkeypatch, metadata=metadata)
    with pytest.raises(BadRequestError):
        await harness.service.connect(
            user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
        )
    catalog.direct_tool_names.assert_not_awaited()
    harness.provider.create_link_session.assert_not_awaited()
    assert not harness.store


@pytest.mark.security
@pytest.mark.parametrize("pending_is_active", [False, True])
async def test_dynamic_reconnect_replaces_only_the_abandoned_pending_account(
    harness, monkeypatch, pending_is_active
):
    dynamic_catalog(monkeypatch)
    harness.provider.create_link_session.return_value = "trs_salesforce"
    harness.provider.link_session.return_value = ComposioLink(
        connected_account_id="ca_pending",
        redirect_url="https://connect.composio.dev/link/salesforce",
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )
    first = await harness.service.connect(
        user_id=harness.user_id, data=AppConnectionCreate(toolkit="salesforce")
    )
    connection = harness.store[first.connection_id]
    active_account = "ca_pending" if pending_is_active else "ca_active"
    connection.composio_account_id = active_account
    connection.composio_status = "ACTIVE"
    harness.provider.link_session.return_value = ComposioLink(
        connected_account_id="ca_replacement",
        redirect_url="https://connect.composio.dev/link/replacement",
        expires_at=datetime.now(UTC) + timedelta(minutes=20),
    )

    second = await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)

    assert second.attempt_id != first.attempt_id
    assert connection.composio_account_id == active_account
    assert lifecycle._pending(connection, user_id=harness.user_id).account_id == "ca_replacement"
    if pending_is_active:
        harness.provider.delete_account.assert_not_awaited()
    else:
        harness.provider.delete_account.assert_awaited_once_with("ca_pending")
    assert harness.provider.create_link_session.await_count == 2
    harness.provider.link.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize(
    "tools",
    [None, [], ["SALESFORCE_SEARCH_RECORDS"] * 1001, [123], ["../execute"], ["COMPOSIO_EXECUTE"]],
)
async def test_dynamic_reconnect_refuses_an_invalid_saved_action_set_before_provider_io(
    harness, tools
):
    connection = row(
        harness.user_id,
        catalog_key="composio-salesforce",
        url="https://backend.composio.dev/api/v3.1/toolkits/salesforce",
        allowed_tools=tools,
    )
    harness.store[connection.id] = connection
    with pytest.raises(BadRequestError, match="supported catalog"):
        await harness.service.reconnect(user_id=harness.user_id, connection_id=connection.id)
    harness.provider.create_link_session.assert_not_awaited()
    harness.provider.link_session.assert_not_awaited()
    harness.provider.delete_account.assert_not_awaited()
    assert connection.oauth_pending_payload is None


@pytest.mark.security
@pytest.mark.parametrize("dynamic", [False, True])
async def test_pending_account_verification_requires_its_authorization_identity(harness, dynamic):
    connection = row(harness.user_id)
    pending = lifecycle._PendingConsent(
        attempt_id=uuid4(),
        user_id=harness.user_id,
        toolkit="gmail",
        account_id="ca_pending",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        dynamic=dynamic,
    )
    with pytest.raises(ExternalServiceError, match="unavailable"):
        await harness.service._verify_pending_account(
            connection, user_id=harness.user_id, client=harness.provider, pending=pending
        )
    harness.provider.discover_account_auth_config.assert_not_awaited()
    harness.provider.verify_account.assert_not_awaited()
    assert connection.oauth_payload is None


@pytest.mark.security
async def test_curated_connect_fails_closed_if_configuration_lookup_breaks_its_contract(
    harness, monkeypatch
):
    # Fault injection: None is not a supported return from _auth_config. The
    # service's final defense must not turn this into dynamic authorization.
    monkeypatch.setattr(lifecycle, "_auth_config", lambda toolkit: None)
    with pytest.raises(ConfigurationError, match="managed authorization"):
        await start(harness)
    harness.provider.link.assert_not_awaited()
    harness.provider.create_link_session.assert_not_awaited()
    harness.provider.link_session.assert_not_awaited()


@pytest.mark.security
async def test_dynamic_start_fails_closed_if_descriptor_lookup_misses_an_empty_action_set(
    harness, monkeypatch
):
    # Fault injection at the descriptor collaborator; the start boundary keeps
    # its own action ceiling even if a future resolver forgets to validate it.
    monkeypatch.setattr(lifecycle, "_app", lambda connection: APPS[0])
    connection = row(harness.user_id, allowed_tools=[])
    with pytest.raises(BadRequestError, match="action list"):
        await harness.service._start_dynamic(connection, user_id=harness.user_id)
    harness.provider.create_link_session.assert_not_awaited()
    harness.provider.link_session.assert_not_awaited()
    harness.provider.delete_account.assert_not_awaited()
    assert connection.oauth_pending_payload is None
