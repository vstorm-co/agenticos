"""Native tools and pollers keep their principal, source policy and consumed position."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.agents.watch_sources import WatchReadReceipt
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.schemas.watch_sources import WatchSources
from app.services.integrations import build_watch_toolset, feeds, poll_account, triggers, watch
from app.services.integrations.service import AccountSelection, IntegrationService
from app.services.mcp_connection import McpConnectionService
from app.services.portals import PolledEvent, PolledEvents

pytestmark = pytest.mark.anyio


def account(provider="google", **changes):
    return McpConnection(
        **(
            {
                "id": uuid4(),
                "catalog_key": provider,
                "scope": "user",
                "purpose": "account",
                "user_id": uuid4(),
                "account_source_organization_id": uuid4(),
                "is_enabled": True,
                "authorization_generation": uuid4(),
                "url": "https://integration.invalid/account",
                "account_email": "member@example.com",
                "name": "Work",
                "auth_type": "oauth",
                "poll_cursor": None,
            }
            | changes
        )
    )


@pytest.fixture
def native_watch(monkeypatch):
    row = account()
    org, person, agent, watch_id = row.account_source_organization_id, row.user_id, uuid4(), uuid4()
    saved = SimpleNamespace(
        id=watch_id,
        connection_id=row.id,
        organization_id=org,
        user_id=person,
        integration_cursor={"old": "position"},
    )
    sources = WatchSources(
        connection_id=row.id,
        authorization_generation=row.authorization_generation,
        catalog_key=row.catalog_key,
        endpoint_hash=hashlib.sha256(row.url.encode()).hexdigest(),
        integration_product_id="gmail",
    )

    @asynccontextmanager
    async def db_context():
        yield AsyncMock()

    monkeypatch.setattr(watch, "get_db_context", db_context)
    monkeypatch.setattr(watch.mcp_connection_repo, "get_account", AsyncMock(return_value=row))
    monkeypatch.setattr(watch.watch_repo, "get_by_id", AsyncMock(return_value=saved))
    monkeypatch.setattr(
        McpConnectionService,
        "integration_access_token",
        AsyncMock(return_value=SecretStr("long-test-token")),
    )
    read = AsyncMock(
        return_value=feeds.Changes(
            events=[feeds.Change(id="new", payload={"text": "hello"})], cursor={"new": "position"}
        )
    )
    monkeypatch.setattr(watch, "changes_since", read)
    receipt = WatchReadReceipt(check=AsyncMock())

    def tool(approved=sources, evidence=receipt, identifier=watch_id):
        return (
            build_watch_toolset(
                approved,
                evidence,
                organization_id=org,
                person_id=person,
                watch_id=identifier,
                agent_id=agent,
            )
            .tools["read_integration_changes"]
            .function
        )

    return row, saved, sources, receipt, read, tool


async def test_watch_has_one_argument_free_tool_and_never_commits_before_consumption(native_watch):
    row, saved, sources, receipt, read, tool = native_watch
    call = tool()
    first = await call()
    second = await call()
    assert first == second == {"events": [{"id": "new", "payload": {"text": "hello"}}]}
    read.assert_awaited_once()
    assert read.await_args.kwargs["cursor"] == {"old": "position"}
    assert receipt.integration_cursor == {"new": "position"}
    assert saved.integration_cursor == {"old": "position"}
    assert receipt.check.await_count == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "org"),
        ("purpose", "mcp"),
        ("is_enabled", False),
        ("user_id", uuid4()),
        ("authorization_generation", uuid4()),
        ("catalog_key", "microsoft"),
        ("url", "https://other.example"),
        ("account_source_organization_id", uuid4()),
    ],
)
async def test_watch_rechecks_the_approved_identity_before_reading(native_watch, field, value):
    row, saved, sources, receipt, read, tool = native_watch
    setattr(row, field, value)
    with pytest.raises(AuthorizationError):
        await tool()()
    read.assert_not_awaited()
    assert receipt.integration_cursor is None


@pytest.mark.parametrize("absent", ["account", "watch", "check", "id", "product"])
async def test_watch_without_its_authority_or_source_cannot_read(native_watch, monkeypatch, absent):
    row, saved, sources, receipt, read, tool = native_watch
    if absent == "account":
        monkeypatch.setattr(watch.mcp_connection_repo, "get_account", AsyncMock(return_value=None))
    if absent == "watch":
        monkeypatch.setattr(watch.watch_repo, "get_by_id", AsyncMock(return_value=None))
    if absent == "check":
        receipt.check = None
    if absent == "id":
        call = tool(identifier=None)
    elif absent == "product":
        call = tool(approved=sources.model_copy(update={"integration_product_id": None}))
    else:
        call = tool()
    with pytest.raises(AuthorizationError):
        await call()
    read.assert_not_awaited()


async def test_failed_provider_read_leaves_pending_watch_position_unset(native_watch, monkeypatch):
    row, saved, sources, receipt, read, tool = native_watch
    monkeypatch.setattr(
        McpConnectionService, "integration_access_token", AsyncMock(return_value=None)
    )
    with pytest.raises(BadRequestError, match="Reconnect"):
        await tool()()
    assert receipt.integration_cursor is None
    read.assert_not_awaited()


@pytest.mark.parametrize(
    "product,provider,method",
    [("imap_mail", "imap", "imap"), ("teams", "microsoft", "application")],
)
async def test_watch_uses_the_same_imap_and_application_teams_feeds_as_triggers(
    native_watch, monkeypatch, product, provider, method
):
    from app.services.integrations import imap, teams_feed

    row, saved, sources, receipt, read, tool = native_watch
    row.catalog_key, row.auth_type = provider, method
    sources = sources.model_copy(
        update={"catalog_key": provider, "integration_product_id": product}
    )
    saved.integration_cursor = None
    if product == "imap_mail":
        monkeypatch.setattr(
            McpConnectionService, "integration_mail_credential", lambda *args, **kwargs: object()
        )
        feed = AsyncMock(return_value=([{"uid": 3}], {"uidvalidity": 9, "last_uid": 3}))
        monkeypatch.setattr(imap, "changed_mail", feed)
    else:
        feed = AsyncMock(return_value=feeds.Changes(cursor={"link": "delta"}))
        monkeypatch.setattr(teams_feed, "changes", feed)
    await tool(approved=sources)()
    assert feed.await_count == 1 and receipt.integration_cursor
    read.assert_not_awaited()


@pytest.fixture
def poller(monkeypatch):
    row = account()
    rows = []
    service = SimpleNamespace(
        polled_source_admissions=AsyncMock(return_value={}),
        prepare_polled_fires=AsyncMock(return_value=[]),
        queue_fire=AsyncMock(),
        polled_places=AsyncMock(return_value={"|inbox": datetime.min.replace(tzinfo=UTC)}),
    )
    monkeypatch.setattr(
        triggers.agent_trigger_repo,
        "list_for_connection",
        AsyncMock(side_effect=lambda *args, **kwargs: rows),
    )
    monkeypatch.setattr("app.services.agent_trigger.AgentTriggerService", lambda db: service)
    monkeypatch.setattr(
        McpConnectionService,
        "integration_access_token",
        AsyncMock(return_value=SecretStr("long-test-token")),
    )
    store = AsyncMock()
    monkeypatch.setattr(McpConnectionService, "store_poll_cursor", store)

    def add(key, config):
        trigger = AgentTrigger(
            id=uuid4(), is_active=True, portal_key=key, connection_id=row.id, event_config=config
        )
        rows.append(trigger)
        service.polled_source_admissions.return_value[trigger.id] = uuid4()
        return trigger

    return row, rows, service, store, add


@pytest.mark.parametrize(
    "key,provider",
    [
        ("slack", "slack"),
        ("teams", "microsoft"),
        ("google_sheets", "google"),
        ("imap", "imap"),
        ("google", "google"),
    ],
)
async def test_native_polling_queues_before_recording_the_consumed_position(
    poller, monkeypatch, key, provider
):
    from app.services.integrations import imap

    row, rows, service, store, add = poller
    row.catalog_key = provider
    config = (
        {"spreadsheet_id": "book", "sheet_name": "Sheet1"}
        if key == "google_sheets"
        else {"channels": ["C1"]}
    )
    trigger = add(key, config)
    service.prepare_polled_fires.return_value = [
        SimpleNamespace(
            trigger_id=trigger.id, event_context="matched event", source_policy_id=uuid4()
        )
    ]
    read = AsyncMock(
        return_value=feeds.Changes(
            events=[feeds.Change(id="one", payload={})], cursor={"resume": "here"}
        )
    )
    monkeypatch.setattr(triggers, "changes_since", read)
    monkeypatch.setattr(triggers, "rows_since", read)
    monkeypatch.setattr(
        McpConnectionService, "integration_mail_credential", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(
        imap,
        "changed_mail",
        AsyncMock(return_value=([{"uid": 7}], {"uidvalidity": 1, "last_uid": 7})),
    )
    adapter = SimpleNamespace(
        poll=AsyncMock(
            return_value=PolledEvents(
                events=(PolledEvent(delivery_id="one", payload={}),), cursor={"resume": "here"}
            )
        )
    )
    monkeypatch.setattr(triggers, "get_adapter", lambda key: adapter)
    queued = await poll_account(AsyncMock(info={}), row)
    assert queued == 1
    assert (
        service.queue_fire.await_args.kwargs["source_policy_id"]
        == service.prepare_polled_fires.return_value[0].source_policy_id
    )
    cursor = store.await_args.kwargs["cursor"]
    assert list(cursor["products"]) == [key]
    assert row.poll_cursor is None


async def test_polling_never_reads_unapproved_or_disabled_triggers(poller):
    row, rows, service, store, add = poller
    row.catalog_key = "slack"
    add("slack", {"channels": ["C1"]})
    service.polled_source_admissions.return_value = {}
    rows.append(AgentTrigger(id=uuid4(), is_active=False, portal_key="slack"))
    assert await triggers.poll_account(AsyncMock(info={}), row) == 0
    service.prepare_polled_fires.assert_not_awaited()
    assert store.await_args.kwargs["cursor"] == {"products": {}}


async def test_a_failed_queue_leaves_the_source_position_unwritten(poller, monkeypatch):
    row, rows, service, store, add = poller
    row.catalog_key = "slack"
    trigger = add("slack", {"channels": ["C1"]})
    monkeypatch.setattr(
        triggers, "changes_since", AsyncMock(return_value=feeds.Changes(cursor={"resume": "new"}))
    )
    service.prepare_polled_fires.return_value = [
        SimpleNamespace(trigger_id=trigger.id, event_context="event", source_policy_id=uuid4())
    ]
    service.queue_fire.side_effect = RuntimeError("transaction failed")
    with pytest.raises(RuntimeError):
        await triggers.poll_account(AsyncMock(info={}), row)
    store.assert_not_awaited()


async def test_orphan_personal_account_cannot_be_polled(poller):
    row, rows, service, store, add = poller
    row.account_source_organization_id = None
    with pytest.raises(BadRequestError):
        await triggers.poll_account(AsyncMock(info={}), row)


@pytest.mark.parametrize("key", ["microsoft", "outlook_calendar", "microsoft_files"])
async def test_application_triggers_keep_the_subject_in_the_reused_graph_adapter(
    poller, monkeypatch, key
):
    row, rows, service, store, add = poller
    row.catalog_key, row.auth_type = "microsoft", "application"
    add(key, {})
    module, cls = {
        "microsoft": ("outlook", "OutlookPortalAdapter"),
        "outlook_calendar": ("outlook_calendar", "OutlookCalendarPortalAdapter"),
        "microsoft_files": ("microsoft_files", "MicrosoftFilesPortalAdapter"),
    }[key]
    chosen = []

    def adapter(*, subject):
        chosen.append(subject)
        return SimpleNamespace(poll=AsyncMock(return_value=PolledEvents(events=(), cursor={})))

    monkeypatch.setattr(f"app.services.portals.{module}.{cls}", adapter)
    await triggers.poll_account(AsyncMock(info={}), row)
    assert chosen == [row.account_email]


async def test_slack_my_mentions_cannot_be_retargeted_by_a_model(monkeypatch):
    row = account("slack", granted_scopes=["search:read"])
    service = IntegrationService(AsyncMock())
    monkeypatch.setattr(service, "account", AsyncMock(return_value=row))
    monkeypatch.setattr(
        McpConnectionService,
        "integration_access_token",
        AsyncMock(return_value=SecretStr("long-test-token")),
    )
    execute = AsyncMock(side_effect=[{"user_id": "U1"}, {"ok": True}])
    monkeypatch.setattr("app.services.integrations.client.execute", execute)
    await service.run(
        "slack",
        "my_mentions",
        AccountSelection(),
        organization_id=uuid4(),
        person_id=row.user_id,
        parameters={},
        query={"count": "10"},
        body=None,
    )
    assert execute.await_args.kwargs["query"] == {"count": "10", "query": "<@U1>"}


@pytest.mark.parametrize(
    "method,missing",
    [
        ("source", False),
        ("source", True),
        ("tool", True),
        ("application", False),
        ("application", True),
        ("imap", False),
    ],
)
async def test_credentials_are_spent_only_by_the_declared_surface(monkeypatch, method, missing):
    from app.services.integrations import imap

    service = IntegrationService(AsyncMock())
    row = account(
        "microsoft" if method == "application" else "imap" if method == "imap" else "google",
        granted_scopes=["Mail.Read", "mail:read", "https://www.googleapis.com/auth/gmail.readonly"],
        auth_type="application" if method == "application" else "oauth",
    )
    if method == "application" and missing:
        row.account_email = None
    monkeypatch.setattr(service, "account", AsyncMock(return_value=row))
    token = AsyncMock(
        return_value=None if missing and method != "application" else SecretStr("long-test-token")
    )
    monkeypatch.setattr(McpConnectionService, "integration_access_token", token)
    execute = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("app.services.integrations.client.execute", execute)
    if method == "source":
        row.granted_scopes.append("https://www.googleapis.com/auth/drive.readonly")
        if missing:
            with pytest.raises(AuthorizationError):
                await service.source_token(
                    organization_id=uuid4(), connection_id=row.id, provider="google"
                )
        else:
            credential = await service.source_token(
                organization_id=uuid4(), connection_id=row.id, provider="google"
            )
            assert credential.connection_id == row.id and credential.provider == "google"
        return
    product = (
        "outlook_mail" if method == "application" else "imap_mail" if method == "imap" else "gmail"
    )
    operation = (
        "read_message"
        if method == "imap"
        else "search_threads"
        if product == "gmail"
        else "search_messages"
    )
    if method == "imap":
        monkeypatch.setattr(
            McpConnectionService, "integration_mail_credential", lambda *args, **kwargs: object()
        )
        monkeypatch.setattr(imap, "execute_mail", AsyncMock(return_value={"uid": 3}))
    if missing:
        with pytest.raises(AuthorizationError):
            await service.run(
                product,
                operation,
                AccountSelection(),
                organization_id=uuid4(),
                person_id=row.user_id,
                parameters={},
                query={},
                body=None,
            )
    else:
        await service.run(
            product,
            operation,
            AccountSelection(),
            organization_id=uuid4(),
            person_id=row.user_id,
            parameters={},
            query={},
            body=None,
        )
        if method == "application":
            assert "/users/member%40example.com/" in execute.await_args.args[0].url


@pytest.mark.parametrize("operation,disabled", [("unknown", False), ("search_messages", True)])
async def test_removed_or_unknown_tools_are_refused_before_any_account_lookup(
    monkeypatch, operation, disabled
):
    service = IntegrationService(AsyncMock())
    resolve = AsyncMock()
    monkeypatch.setattr(service, "account", resolve)
    selection = AccountSelection(disabled_tools=["gmail_search_messages"] if disabled else [])
    with pytest.raises(AuthorizationError if disabled else BadRequestError):
        await service.run(
            "gmail",
            operation,
            selection,
            organization_id=uuid4(),
            person_id=uuid4(),
            parameters={},
            query={},
            body=None,
        )
    resolve.assert_not_awaited()

    from app.agents.capabilities import get

    with pytest.raises(BadRequestError):
        get("gmail").validate_config({"disabled_tools": ["slack_post_message"]})


@pytest.mark.parametrize(
    "identity,query", [({}, {}), ({"user_id": "U"}, {"query": "someone else"})]
)
async def test_my_mentions_requires_identity_and_a_fixed_query(monkeypatch, identity, query):
    service = IntegrationService(AsyncMock())
    row = account("slack", granted_scopes=["search:read"])
    monkeypatch.setattr(service, "account", AsyncMock(return_value=row))
    monkeypatch.setattr(
        McpConnectionService,
        "integration_access_token",
        AsyncMock(return_value=SecretStr("long-test-token")),
    )
    execute = AsyncMock(return_value=identity)
    monkeypatch.setattr("app.services.integrations.client.execute", execute)
    with pytest.raises(BadRequestError):
        await service.run(
            "slack",
            "my_mentions",
            AccountSelection(),
            organization_id=uuid4(),
            person_id=row.user_id,
            parameters={},
            query=query,
            body=None,
        )
    assert execute.await_count == 1


@pytest.mark.parametrize("key", ["unknown", "github"])
async def test_nonpolling_portals_are_never_read_by_native_poller(poller, key):
    row, rows, service, store, add = poller
    add(key, {})
    assert await triggers.poll_account(AsyncMock(info={}), row) == 0
    service.polled_source_admissions.assert_not_awaited()


async def test_native_poller_refuses_a_revoked_token(poller, monkeypatch):
    row, rows, service, store, add = poller
    row.catalog_key = "slack"
    add("slack", {"channels": ["C"]})
    monkeypatch.setattr(
        McpConnectionService, "integration_access_token", AsyncMock(return_value=None)
    )
    assert await triggers.poll_account(AsyncMock(info={}), row) == 0
    assert store.await_args.kwargs["cursor"] == {"products": {}}


async def test_native_poller_reuses_the_same_application_teams_feed(poller, monkeypatch):
    from app.services.integrations import teams_feed

    row, rows, service, store, add = poller
    row.catalog_key, row.auth_type = "microsoft", "application"
    add("teams", {})
    feed = AsyncMock(return_value=feeds.Changes(cursor={"link": "delta"}))
    monkeypatch.setattr(teams_feed, "changes", feed)
    await triggers.poll_account(AsyncMock(info={}), row)
    assert feed.await_args.kwargs == {
        "channels": (),
        "application": True,
        "subject": row.account_email,
    }


async def test_native_poller_refuses_a_missing_provider_adapter(poller, monkeypatch):
    row, rows, service, store, add = poller
    add("google", {})
    monkeypatch.setattr(triggers, "get_adapter", lambda key: None)
    assert await triggers.poll_account(AsyncMock(info={}), row) == 0
    assert store.await_args.kwargs["cursor"] == {"products": {}}


async def test_poller_never_sends_one_providers_token_to_another(poller, monkeypatch):
    row, rows, service, store, add = poller
    add("slack", {"channels": ["C1"]})
    token = AsyncMock()
    monkeypatch.setattr(McpConnectionService, "integration_access_token", token)
    with pytest.raises(BadRequestError, match="another integration provider"):
        await triggers.poll_account(AsyncMock(info={}), row)
    token.assert_not_awaited()
    store.assert_not_awaited()


async def test_odoo_watch_and_trigger_share_the_bounded_record_feed(
    native_watch, poller, monkeypatch
):
    from app.core.odoo_credential import OdooCredential
    from app.services.integrations import odoo_feed

    credential = OdooCredential(
        origin="https://erp.example.com", database="company", api_key="private-key"
    )
    monkeypatch.setattr(
        McpConnectionService, "integration_odoo_credential", lambda *args, **kwargs: credential
    )
    read = AsyncMock(
        return_value=feeds.Changes(
            events=[feeds.Change(id="record:7", payload={"product_id": "odoo_contacts"})],
            cursor={"models": {"res.partner": {"id": 7}}},
        )
    )
    monkeypatch.setattr(odoo_feed, "changes", read)
    row, saved, sources, receipt, old_read, tool = native_watch
    row.catalog_key, row.auth_type = "odoo", "odoo"
    sources = sources.model_copy(
        update={"catalog_key": "odoo", "integration_product_id": "odoo_contacts"}
    )
    await tool(approved=sources)()
    assert receipt.integration_cursor == {"models": {"res.partner": {"id": 7}}}
    old_read.assert_not_awaited()
    account, rows, service, store, add = poller
    account.catalog_key, account.auth_type = "odoo", "odoo"
    add("odoo_contacts", {"product_id": "odoo_contacts"})
    await triggers.poll_account(AsyncMock(info={}), account)
    assert read.await_args.args[:2] == (credential, "odoo_contacts")
    assert (
        store.await_args.kwargs["cursor"]["products"]["odoo_contacts"] == receipt.integration_cursor
    )


async def test_one_broken_product_does_not_rollback_a_healthy_products_jobs_or_cursor(
    poller, monkeypatch
):
    row, rows, service, store, add = poller
    healthy = add("google", {})
    add("google_sheets", {"spreadsheet_id": "deleted-book", "sheet_name": "Sheet1"})
    service.prepare_polled_fires.return_value = [
        SimpleNamespace(trigger_id=healthy.id, event_context="new mail", source_policy_id=uuid4())
    ]
    monkeypatch.setattr(
        triggers,
        "get_adapter",
        lambda _: SimpleNamespace(
            poll=AsyncMock(return_value=PolledEvents(events=(), cursor={"resume": "mail"}))
        ),
    )
    monkeypatch.setattr(
        triggers, "rows_since", AsyncMock(side_effect=BadRequestError(message="Deleted sheet"))
    )
    db = AsyncMock(info={})
    assert await triggers.poll_account(db, row) == 1
    assert store.await_args.kwargs["cursor"] == {"products": {"google": {"resume": "mail"}}}
    assert service.queue_fire.await_count == 1
    assert db.begin_nested.await_count == 2
