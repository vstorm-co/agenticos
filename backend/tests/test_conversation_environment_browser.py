"""A kept target always has an egress-owning transport or is destroyed."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import anyio.lowlevel
import pytest

from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.browser_use._page import BrowserTarget
from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import ConversationEnvironment
from app.services import conversation_environment_browser as browser
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    EnvironmentAuthority,
)
from app.services.conversation_environment_resources import BrowserEnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    from types import SimpleNamespace

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    conversation = Conversation(
        id=uuid4(), organization_id=ctx.organization_id, user_id=ctx.user_id
    )
    agent = Agent(id=uuid4(), organization_id=ctx.organization_id, name="Browser", slug="browser")
    admitted = EnvironmentAuthority(
        ctx,
        conversation,
        agent,
        uuid4(),
        AgentSpec(name="Browser", instructions="Use the browser"),
        "agent",
        None,
    )
    resolved = BrowserEnvironmentSettings(
        admitted,
        WebBrowserConfig(session_lifetime="conversation"),
        "fingerprint",
        "http://browser:9222",
        None,
    )
    row = ConversationEnvironment(
        id=uuid4(),
        organization_id=ctx.organization_id,
        vault_organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        agent_id=agent.id,
        state="ready",
        kind="browser",
        execution_target="agent",
        session_lifetime="conversation",
        revision=1,
        provisioning_attempt=1,
        resource_ciphertext="sealed",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    payload = ConversationEnvironmentService.payload(row)
    target = BrowserTarget(context_id="owned-context", target_id="owned-page")
    resource = BrowserEnvironmentResource(
        environment_id=row.id,
        organization_id=ctx.organization_id,
        cdp_url="http://browser:9222",
        tabs={"main": target},
    )
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(browser, "get_worker_db_context", session)
    monkeypatch.setattr(browser.environments, "for_worker", AsyncMock(return_value=row))
    monkeypatch.setattr(browser, "current_actor", AsyncMock(return_value=ctx))
    monkeypatch.setattr(
        browser.ConversationEnvironmentService, "claim", AsyncMock(return_value=resolved)
    )
    monkeypatch.setattr(
        browser.ConversationEnvironmentService,
        "live",
        AsyncMock(return_value=(row, resolved, resource)),
    )
    monkeypatch.setattr(
        browser.ConversationEnvironmentService, "resource", lambda _self, _row, _org: resource
    )
    monkeypatch.setattr(browser.ConversationEnvironmentService, "expire", AsyncMock())
    monkeypatch.setattr(browser.browser_sign_in, "load_for", AsyncMock(return_value=[]))
    return SimpleNamespace(
        ctx=ctx,
        resolved=resolved,
        row=row,
        payload=payload,
        target=target,
        resource=resource,
        db=db,
    )


async def test_ready_target_stays_guarded_after_provision_returns_and_ends_on_owner_exit(
    case, monkeypatch
):
    entered, detached, stop = anyio.Event(), anyio.Event(), anyio.Event()

    @asynccontextmanager
    async def page(**options):
        await options["keep"](case.target)
        entered.set()
        try:
            yield AsyncMock()
        finally:
            detached.set()

    async def alive(_payload, _target):
        await stop.wait()
        return False

    monkeypatch.setattr(browser, "open_page", page)
    monkeypatch.setattr(browser, "_still_owned", alive)
    keep = AsyncMock()
    actual = await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=keep)
    assert entered.is_set() and actual == case.target
    assert not detached.is_set()
    keep.assert_awaited_once_with(case.target)
    stop.set()
    with anyio.fail_after(2):
        await detached.wait()
    # Settle the tracked task, not just its transport.
    await anyio.lowlevel.checkpoint()
    assert browser.ConversationEnvironmentService.expire.await_count == 1


async def test_failed_creation_propagates_without_claiming_a_live_resource(case, monkeypatch):
    @asynccontextmanager
    async def page(**_options):
        raise OSError("provider refused creation")
        yield

    monkeypatch.setattr(browser, "open_page", page)
    with pytest.raises(OSError):
        await browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
    browser.ConversationEnvironmentService.expire.assert_not_awaited()


async def test_caller_cancellation_before_ready_cancels_and_joins_the_owner(case, monkeypatch):
    opening, closed = anyio.Event(), anyio.Event()

    @asynccontextmanager
    async def page(**_options):
        opening.set()
        try:
            await anyio.sleep_forever()
            yield
        finally:
            closed.set()

    monkeypatch.setattr(browser, "open_page", page)
    caller = asyncio.create_task(
        browser.retain_tab(case.resolved, case.payload, start_url=None, keep=AsyncMock())
    )
    await opening.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert closed.is_set()


async def test_guard_authority_survives_completed_producer_for_conversation_lifetime(
    case, monkeypatch
):
    case.row.source_run_id = uuid4()
    monkeypatch.setattr(browser.run_repo, "get_run", AsyncMock(return_value=None))
    assert await browser._still_owned(case.payload, case.target)
    browser.run_repo.get_run.assert_not_awaited()
    case.row.session_lifetime = "run"
    assert not await browser._still_owned(case.payload, case.target)


@pytest.mark.parametrize(
    "change", ["missing", "tenant", "revision", "expired", "owner", "removed", "revoked"]
)
async def test_guard_stops_for_stale_owner_or_removed_target(case, monkeypatch, change):
    if change == "missing":
        browser.environments.for_worker.return_value = None
    elif change == "tenant":
        case.row.organization_id = uuid4()
    elif change == "revision":
        case.row.revision += 1
    elif change == "expired":
        case.row.state = "expired"
    elif change == "owner":
        case.row.user_id = None
    elif change == "removed":
        case.resource.tabs = {}
    else:
        browser.current_actor.side_effect = AuthorizationError(message="Membership revoked")
    assert not await browser._still_owned(case.payload, case.target)


async def test_starting_owner_uses_provision_fence_but_ready_owner_does_not(case):
    case.row.state = "starting"
    assert await browser._still_owned(case.payload, case.target)
    browser.ConversationEnvironmentService.claim.assert_awaited_once()
    browser.ConversationEnvironmentService.claim.side_effect = AuthorizationError(
        message="Producer no longer allowed"
    )
    assert not await browser._still_owned(case.payload, case.target)
    case.row.state = "ready"
    assert await browser._still_owned(case.payload, case.target)
    assert browser.ConversationEnvironmentService.claim.await_count == 2


async def test_closing_one_tab_never_expires_its_siblings(case):
    case.resource.tabs = {"sibling": BrowserTarget(context_id="other", target_id="other-page")}
    await browser._ended(case.payload, case.target)
    browser.ConversationEnvironmentService.expire.assert_not_awaited()


@pytest.mark.parametrize("change", ["missing", "scope", "revision", "expired"])
async def test_old_guard_cannot_expire_a_replacement_or_already_ended_environment(case, change):
    if change == "missing":
        browser.environments.for_worker.return_value = None
    elif change == "scope":
        case.row.vault_organization_id = uuid4()
    elif change == "revision":
        case.row.revision += 1
    else:
        case.row.state = "expired"
    await browser._ended(case.payload, case.target)
    browser.ConversationEnvironmentService.expire.assert_not_awaited()
