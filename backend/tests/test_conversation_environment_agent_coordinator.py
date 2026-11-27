"""Real-run adoption coordinates durable admission, current authority and physical leases."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use import WebBrowserConfig
from app.agents.capabilities.browser_use._loop import PageSession
from app.agents.capabilities.browser_use._page import BrowserTarget, PagePolicy
from app.agents.capabilities.computer_use._actions import TypeText
from app.agents.spec import AgentSpec
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.conversation_environment import ConversationEnvironment
from app.schemas.conversation_environment import (
    ConversationEnvironmentRead,
    ConversationEnvironmentRefusal,
)
from app.services import conversation_environment_agent as adapter
from app.services.conversation_environment_driver import EnvironmentDriver
from app.services.conversation_environment_policy import (
    BrowserEnvironmentSettings,
    EnvironmentAuthority,
    EnvironmentNotReady,
)
from app.services.conversation_environment_resources import BrowserEnvironmentResource
from app.worker.jobs import ConversationEnvironmentPayload
from tests.test_conversation_environment_agent import PAGE_OPERATIONS

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class Case:
    owner: adapter.AgentEnvironment
    row: ConversationEnvironment
    resolved: BrowserEnvironmentSettings
    resource: BrowserEnvironmentResource
    service: AsyncMock
    driver: AsyncMock
    events: list[str]

    def state(self, **changes) -> ConversationEnvironmentRead:
        return ConversationEnvironmentRead(
            id=self.row.id,
            kind="browser",
            execution_target="agent",
            agent_id=self.row.agent_id,
            state="ready",
            session_lifetime="conversation",
            idle_seconds=900,
            control="none",
            can_control=True,
            expires_at=self.row.expires_at,
            refusal=None,
        ).model_copy(update=changes)

    def payload(self) -> ConversationEnvironmentPayload:
        return ConversationEnvironmentPayload(
            environment_id=self.row.id,
            organization_id=self.owner.ctx.organization_id,
            revision=1,
        )


@pytest.fixture
def case(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    owner = adapter.AgentEnvironment(
        ctx,
        conversation_id=uuid4(),
        agent_id=uuid4(),
        version_id=uuid4(),
        run_id=uuid4(),
        target="agent",
        kind="browser",
    )
    authority = EnvironmentAuthority(
        ctx,
        Conversation(
            id=owner.conversation_id, organization_id=ctx.organization_id, user_id=ctx.user_id
        ),
        Agent(id=owner.agent_id, organization_id=ctx.organization_id),
        owner.version_id,
        AgentSpec(name="Browser"),
        "agent",
        None,
    )
    resolved = BrowserEnvironmentSettings(
        authority,
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
        conversation_id=owner.conversation_id,
        agent_id=owner.agent_id,
        agent_version_id=uuid4(),
        source_run_id=owner.run_id,
        kind="browser",
        execution_target="agent",
        state="ready",
        session_lifetime="conversation",
        idle_seconds=900,
        fingerprint="fingerprint",
        revision=1,
        provisioning_attempt=1,
        resource_key="physical-resource",
        resource_ciphertext="sealed",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    resource = BrowserEnvironmentResource(
        environment_id=row.id,
        organization_id=ctx.organization_id,
        cdp_url="http://browser:9222",
        tabs={"main": BrowserTarget(context_id="same-context", target_id="same-target")},
    )
    service = AsyncMock(spec=adapter.ConversationEnvironmentService)
    driver = AsyncMock(spec=EnvironmentDriver)
    driver.token = uuid4()
    events = []
    fixture = Case(owner, row, resolved, resource, service, driver, events)
    service.read.return_value = fixture.state()
    service.ensure.return_value = fixture.state(state="starting")
    service.live.return_value = row, resolved, resource
    service.payload = MagicMock(return_value=fixture.payload())
    service.resource = MagicMock(return_value=resource)

    @asynccontextmanager
    async def database():
        events.append("enter")
        try:
            yield AsyncMock()
        finally:
            events.append("exit")

    monkeypatch.setattr(adapter, "get_db_context", database)
    monkeypatch.setattr(adapter, "ConversationEnvironmentService", MagicMock(return_value=service))
    monkeypatch.setattr(adapter, "EnvironmentDriver", MagicMock(return_value=driver))
    monkeypatch.setattr(adapter.environments, "for_worker", AsyncMock(return_value=row))
    monkeypatch.setattr(adapter.environments, "owned", AsyncMock(return_value=row))
    monkeypatch.setattr(
        adapter.environments,
        "driver",
        AsyncMock(
            return_value=SimpleNamespace(
                lease_token=driver.token, lease_until=datetime.now(UTC) + timedelta(minutes=1)
            )
        ),
    )
    monkeypatch.setattr(adapter.runtime, "start_environment", AsyncMock())
    monkeypatch.setattr(adapter.runtime, "dispose", AsyncMock())
    return fixture


async def test_ready_adoption_preserves_creation_provenance_and_checks_cached_driver(case):
    assert case.row.agent_version_id != case.owner.version_id
    assert await case.owner.acquire()
    assert case.owner.environment_id == case.row.id
    assert await case.owner.acquire()
    case.driver.acquire.assert_awaited_once()
    case.driver.require.assert_awaited_once()
    case.service.ensure.assert_not_awaited()
    adapter.runtime.start_environment.assert_not_awaited()


async def test_run_lifetime_browser_without_ready_resource_keeps_legacy_run_path(case):
    case.service.read.return_value = case.state(state="not_started", session_lifetime="run")
    assert not await case.owner.acquire()
    assert not await case.owner.acquire()
    case.service.read.assert_awaited_once()
    case.service.ensure.assert_not_awaited()


async def test_nonrecoverable_readiness_refusal_does_not_provision(case):
    case.service.read.return_value = case.state(
        state="failed",
        refusal=ConversationEnvironmentRefusal(code="capacity_reached", message="Full"),
    )
    with pytest.raises(EnvironmentNotReady, match="Full"):
        await case.owner.acquire()
    case.service.ensure.assert_not_awaited()


@pytest.mark.parametrize("missing", ["id", "row", "producer"])
async def test_incomplete_or_foreign_admission_never_starts_provider(case, monkeypatch, missing):
    case.service.read.return_value = case.state(state="expired")
    if missing == "id":
        case.service.ensure.return_value = case.state(id=None, state="starting")
    elif missing == "row":
        adapter.environments.for_worker.return_value = None
    else:
        case.row.source_run_id = uuid4()
    with pytest.raises((EnvironmentNotReady, ConflictError)):
        await case.owner.acquire()
    adapter.runtime.start_environment.assert_not_awaited()


async def test_first_use_provisions_after_admission_transaction_has_exited(case):
    case.service.read.return_value = case.state(state="expired")

    async def start(payload, *, attempt):
        assert payload == case.payload() and attempt == 1
        assert case.events == ["enter", "exit"]

    adapter.runtime.start_environment.side_effect = start
    assert await case.owner.acquire()
    case.service.ensure.assert_awaited_once()
    assert case.service.ensure.await_args.kwargs["producer_run_id"] == case.owner.run_id
    case.driver.acquire.assert_awaited_once()


async def test_missing_physical_key_refuses_driver_before_provider_access(case):
    case.row.resource_key = None
    with pytest.raises(EnvironmentNotReady, match="physical resource"):
        await case.owner.acquire()
    case.driver.acquire.assert_not_awaited()


async def test_failed_driver_claim_is_closed_before_error_propagates(case):
    case.driver.acquire.side_effect = ConflictError(message="In use")
    with pytest.raises(ConflictError, match="In use"):
        await case.owner.acquire()
    case.driver.close.assert_awaited_once()
    assert case.owner.driver is None


async def test_live_requires_admission_and_current_published_version(case):
    with pytest.raises(EnvironmentNotReady):
        await case.owner.live(AsyncMock())
    case.owner.environment_id = case.row.id
    case.owner.version_id = uuid4()
    with pytest.raises(EnvironmentNotReady, match="published agent version"):
        await case.owner.live(AsyncMock())


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "missing",
        "status",
        "surface",
        "agent_version_id",
        "user_id",
        "agent_id",
        "conversation_id",
    ],
)
async def test_driver_rechecks_real_web_producer_identity(case, monkeypatch, changed):
    case.owner.environment_id = case.row.id
    run = AgentRun(
        id=case.owner.run_id,
        status="running",
        surface="web",
        agent_version_id=case.owner.version_id,
        user_id=case.owner.ctx.user_id,
        agent_id=case.owner.agent_id,
        conversation_id=case.owner.conversation_id,
    )
    if changed not in (None, "missing"):
        setattr(
            run,
            changed,
            "completed" if changed == "status" else "api" if changed == "surface" else uuid4(),
        )
    monkeypatch.setattr(
        adapter.run_repo, "get_run", AsyncMock(return_value=None if changed == "missing" else run)
    )
    if changed is None:
        await case.owner._check(AsyncMock())
    else:
        with pytest.raises(ConflictError, match="no longer active"):
            await case.owner._check(AsyncMock())


async def test_load_and_store_require_driver_and_exact_physical_token(case):
    with pytest.raises(ConflictError, match="does not hold"):
        await case.owner.load()
    with pytest.raises(ConflictError, match="does not hold"):
        await case.owner.store(case.resource)
    case.owner.driver, case.owner.environment_id = case.driver, case.row.id
    assert await case.owner.load() == (case.resolved, case.resource)
    await case.owner.store(case.resource)
    case.service.replace_resource.assert_awaited_once_with(case.row, case.resource)
    for key, lease in [
        (None, None),
        ("physical", None),
        (
            "physical",
            SimpleNamespace(
                lease_token=uuid4(), lease_until=datetime.now(UTC) + timedelta(minutes=1)
            ),
        ),
    ]:
        case.row.resource_key = key
        adapter.environments.driver.return_value = lease
        with pytest.raises(ConflictError, match="driver was lost"):
            await case.owner.store(case.resource)
    assert case.service.replace_resource.await_count == 1


@pytest.mark.parametrize("lifetime,sealed", [("conversation", True), ("run", True), ("run", False)])
async def test_finish_releases_driver_but_only_destroys_run_owned_resource(case, lifetime, sealed):
    case.owner.driver, case.owner.environment_id = case.driver, case.row.id
    case.row.session_lifetime = lifetime
    case.row.resource_ciphertext = "sealed" if sealed else None
    await case.owner.finish()
    await case.owner.finish()
    case.driver.close.assert_awaited_once()
    if lifetime == "conversation":
        case.service.expire.assert_not_awaited()
        adapter.runtime.dispose.assert_not_awaited()
    else:
        case.service.expire.assert_awaited_once_with(case.row)
        if sealed:
            adapter.runtime.dispose.assert_awaited_once_with(case.resource)
            case.service.cleaned.assert_awaited_once_with(case.payload())
        else:
            adapter.runtime.dispose.assert_not_awaited()


async def test_tabs_selection_and_close_preserve_journal_until_disposal_succeeds(case):
    assert case.owner.browser().page_factory == case.owner.page
    assert await case.owner.tabs() == (("main",), "main")
    second = BrowserTarget(context_id="second-context", target_id="second-target")
    case.resource.tabs["second"] = second
    await case.owner.select("second")
    assert case.resource.active == "second"
    with pytest.raises(EnvironmentNotReady):
        await case.owner.select("unknown")
    adapter.runtime.dispose.side_effect = OSError("Disconnected")
    with pytest.raises(OSError):
        await case.owner.close_tab("second")
    assert case.resource.tabs["second"] == second
    adapter.runtime.dispose.side_effect = None
    await case.owner.close_tab("second")
    assert tuple(case.resource.tabs) == ("main",) and case.resource.active == "main"
    await case.owner.close_tab("unknown")


async def test_fallback_tab_operations_do_not_touch_owned_state(case):
    case.owner._fallback = True
    assert await case.owner.tabs() is None
    await case.owner.select("any")
    await case.owner.close_tab("any")
    case.service.live.assert_not_awaited()


@pytest.mark.parametrize("existing", [True, False])
async def test_retained_page_attaches_exact_target_and_only_new_tab_is_provisioned(
    case, monkeypatch, existing
):
    page = AsyncMock(spec=PageSession)
    page.native_id, page.streaming = "target", False
    target = BrowserTarget(context_id="new-context", target_id="new-target")
    calls = []

    @asynccontextmanager
    async def opened(**kwargs):
        calls.append(kwargs)
        yield page

    async def retain(resolved, payload, *, start_url, keep):
        assert resolved is case.resolved and payload == case.payload()
        assert start_url == "https://example.com/new"
        await keep(target)
        return target

    monkeypatch.setattr(adapter, "open_page", opened)
    monkeypatch.setattr(
        "app.services.conversation_environment_browser.retain_tab", AsyncMock(side_effect=retain)
    )
    tab_id = "main" if existing else "new"
    expected = case.resource.tabs["main"] if existing else target
    async with case.owner.page(
        cdp_url="http://ignored:9222",
        start_url="https://example.com/new",
        policy=PagePolicy(allowed_domains=None, candidate_cap=10, preview_width=100),
        sign_ins=[],
        route=None,
        retained_tab_id=tab_id,
    ) as driven:
        assert driven.native_id == "target"
    assert calls[0]["retained"] == expected
    assert calls[0]["cdp_url"] == case.resource.cdp_url
    assert calls[0]["start_url"] is None
    if not existing:
        assert case.resource.active == "new" and case.resource.tabs["new"] == target
        case.service.replace_resource.assert_awaited_once()


async def test_store_refuses_expired_physical_token_and_failed_renewal(case):
    case.owner.driver, case.owner.environment_id = case.driver, case.row.id
    adapter.environments.driver.return_value = SimpleNamespace(
        lease_token=case.driver.token, lease_until=datetime.now(UTC) - timedelta(seconds=1)
    )
    with pytest.raises(ConflictError):
        await case.owner.store(case.resource)
    case.driver.require.side_effect = ConflictError(message="Renewal failed")
    with pytest.raises(ConflictError, match="Renewal failed"):
        await case.owner.store(case.resource)
    case.service.replace_resource.assert_not_awaited()


@pytest.mark.parametrize("method,args", PAGE_OPERATIONS)
async def test_valid_page_driver_forwards_exact_operation_and_result(case, method, args):
    page = AsyncMock(spec=PageSession)
    page.native_id, page.streaming = "actual-target", True
    wrapped = adapter.DrivenPage(page, case.driver)
    result = await getattr(wrapped, method)(*args)
    getattr(page, method).assert_awaited_once_with(*args)
    case.driver.require.assert_awaited_once()
    if method in {"snapshot", "location", "screenshot", "read", "point", "capture_sign_in"}:
        assert result is getattr(page, method).return_value


async def test_desktop_factory_reuses_owned_view_and_close_detaches_then_finishes(
    case, monkeypatch
):
    from app.agents.capabilities.computer_use._backends import Computer

    computer = AsyncMock(spec=Computer)
    computer.label = "Owned desktop"
    events = []

    @asynccontextmanager
    async def opened(resource, resolved):
        assert resource is case.resource and resolved is case.resolved
        try:
            yield adapter.runtime.DesktopEnvironmentView(computer, 1024, 768)
        finally:
            events.append("detached")

    monkeypatch.setattr(adapter.runtime, "open_view", opened)
    fallback = AsyncMock()
    assert case.owner.desktop() is not None
    wrapped = await case.owner.wrap_computer(fallback)(MagicMock())
    await wrapped.capture()
    action = TypeText(text="Draft")
    await wrapped.perform(action)
    computer.perform.assert_awaited_once_with(action)
    await wrapped.apps()
    computer.capture.assert_awaited_once()
    computer.apps.assert_awaited_once()
    await wrapped.close()
    assert events == ["detached"] and case.owner._closed
    fallback.assert_not_awaited()


async def test_legacy_desktop_factory_fallback_does_not_open_owned_view(case, monkeypatch):
    case.owner._fallback = True
    opened = MagicMock()
    monkeypatch.setattr(adapter.runtime, "open_view", opened)
    fallback = AsyncMock()
    workspace = MagicMock()
    assert await case.owner.wrap_computer(fallback)(workspace) is fallback.return_value
    fallback.assert_awaited_once_with(workspace)
    opened.assert_not_called()


async def test_run_browser_fallback_uses_original_page_contract(case, monkeypatch):
    page = AsyncMock(spec=PageSession)
    case.owner._fallback = True
    calls = []

    @asynccontextmanager
    async def opened(**kwargs):
        calls.append(kwargs)
        yield page

    monkeypatch.setattr(adapter, "open_page", opened)
    policy = PagePolicy(allowed_domains=None, candidate_cap=10, preview_width=100)
    async with case.owner.page(
        cdp_url="http://legacy:9222",
        start_url="https://example.com/",
        policy=policy,
        sign_ins=[],
        route=None,
        retained_tab_id="main",
    ) as actual:
        assert actual is page
    assert calls == [
        {
            "cdp_url": "http://legacy:9222",
            "start_url": "https://example.com/",
            "policy": policy,
            "sign_ins": [],
            "route": None,
        }
    ]


async def test_page_refuses_driver_released_during_transport_attachment(case, monkeypatch):
    @asynccontextmanager
    async def opened(**kwargs):
        case.owner.driver = None
        yield AsyncMock(spec=PageSession)

    monkeypatch.setattr(adapter, "open_page", opened)
    with pytest.raises(ConflictError, match="driver was released"):
        async with case.owner.page(
            cdp_url="http://ignored:9222",
            start_url=None,
            policy=PagePolicy(allowed_domains=None, candidate_cap=10, preview_width=100),
            sign_ins=[],
            route=None,
            retained_tab_id="main",
        ):
            pytest.fail("Released control cannot become a driven page")


@pytest.mark.parametrize("operation", ["tabs", "select", "close", "page"])
async def test_changed_resource_kind_never_becomes_browser_io(case, operation):
    from app.services.conversation_environment_resources import DesktopEnvironmentResource

    desktop = DesktopEnvironmentResource(
        environment_id=case.row.id,
        organization_id=case.owner.ctx.organization_id,
        backend="sandbox",
        width=1024,
        height=768,
    )
    case.service.live.return_value = case.row, case.resolved, desktop
    with pytest.raises(EnvironmentNotReady):
        if operation == "tabs":
            await case.owner.tabs()
        elif operation == "select":
            case.owner.driver, case.owner.environment_id = case.driver, case.row.id
            await case.owner.select("main")
        elif operation == "close":
            case.owner.driver, case.owner.environment_id = case.driver, case.row.id
            await case.owner.close_tab("main")
        else:
            async with case.owner.page(
                cdp_url="http://ignored:9222",
                start_url=None,
                policy=PagePolicy(allowed_domains=None, candidate_cap=10, preview_width=100),
                sign_ins=[],
                route=None,
                retained_tab_id="main",
            ):
                pytest.fail("A desktop cannot be adopted as a browser")


async def test_new_browser_tab_cap_refuses_before_replacing_durable_resource(case, monkeypatch):
    case.resource.tabs = {
        str(index): BrowserTarget(context_id=f"context-{index}", target_id=f"target-{index}")
        for index in range(8)
    }

    async def retain(resolved, payload, *, start_url, keep):
        await keep(BrowserTarget(context_id="ninth-context", target_id="ninth-target"))

    monkeypatch.setattr("app.services.conversation_environment_browser.retain_tab", retain)
    with pytest.raises(ConflictError, match="Eight browser tabs"):
        async with case.owner.page(
            cdp_url="http://ignored:9222",
            start_url=None,
            policy=PagePolicy(allowed_domains=None, candidate_cap=10, preview_width=100),
            sign_ins=[],
            route=None,
            retained_tab_id="ninth",
        ):
            pytest.fail("Ninth tab must not be attached")
    assert len(case.resource.tabs) == 8
    case.service.replace_resource.assert_not_awaited()


async def test_finish_missing_row_is_idempotent_without_disposing_unowned_resource(case):
    case.owner.environment_id = case.row.id
    adapter.environments.owned.return_value = None
    await case.owner.finish()
    case.service.expire.assert_not_awaited()
    adapter.runtime.dispose.assert_not_awaited()


async def test_browser_view_is_not_accepted_as_a_desktop_computer():
    from app.agents.capabilities.computer_use._backends import ComputerError

    with pytest.raises(ComputerError, match="changed kind"):
        adapter._desktop_computer(MagicMock(spec=adapter.runtime.BrowserEnvironmentView))


@pytest.mark.parametrize("lifetime", ["run", "conversation"])
async def test_successful_physical_claim_binds_only_run_lifetime_to_actual_adopter(
    case, monkeypatch, lifetime
):
    original_producer = uuid4()
    original_version = case.row.agent_version_id
    case.row.source_run_id = original_producer
    case.row.session_lifetime = lifetime
    producer = AgentRun(
        id=case.owner.run_id,
        status="running",
        surface="web",
        agent_version_id=case.owner.version_id,
        user_id=case.owner.ctx.user_id,
        agent_id=case.owner.agent_id,
        conversation_id=case.owner.conversation_id,
    )
    monkeypatch.setattr(adapter.run_repo, "get_run", AsyncMock(return_value=producer))
    claim_db = AsyncMock()

    async def acquired():
        callback = adapter.EnvironmentDriver.call_args.kwargs["on_acquired"]
        await callback(claim_db)

    case.driver.acquire.side_effect = acquired
    assert await case.owner.acquire()
    assert case.row.source_run_id == (case.owner.run_id if lifetime == "run" else original_producer)
    assert case.row.agent_version_id == original_version
    assert claim_db.flush.await_count == (1 if lifetime == "run" else 0)


async def test_refused_physical_claim_does_not_rebind_run_provenance(case):
    original = case.row.source_run_id = uuid4()
    case.row.session_lifetime = "run"
    case.driver.acquire.side_effect = ConflictError(message="Human still controls the resource")
    with pytest.raises(ConflictError, match="Human still controls"):
        await case.owner.acquire()
    assert case.row.source_run_id == original
    case.driver.close.assert_awaited_once()


async def test_terminal_adopter_cannot_be_bound_after_claim(case, monkeypatch):
    case.owner.environment_id = case.row.id
    case.row.session_lifetime = "run"
    original = case.row.source_run_id = uuid4()
    monkeypatch.setattr(adapter.run_repo, "get_run", AsyncMock(return_value=None))
    db = AsyncMock()
    with pytest.raises(ConflictError, match="no longer active"):
        await case.owner._adopt(db)
    assert case.row.source_run_id == original
    db.flush.assert_not_awaited()


async def test_closing_background_tab_preserves_current_manual_selection(case):
    await case.owner.acquire()
    case.resource.tabs["second"] = BrowserTarget(
        context_id="second-context", target_id="second-target"
    )
    assert case.resource.active == "main"
    await case.owner.close_tab("second")
    assert case.resource.active == "main" and tuple(case.resource.tabs) == ("main",)
