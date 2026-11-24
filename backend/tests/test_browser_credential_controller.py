"""The one native writer commits its claim, protects output and never retries uncertainty."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.browser_use._protected import BrowserOutputGuard
from app.core.browser_fill import (
    BrowserFillHandle,
    BrowserFillObservation,
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillState,
)
from app.core.permissions import AuthContext
from app.schemas.browser_credential import BrowserCredentialPlanRead
from app.services.browser_credentials import _controller as controller
from app.services.browser_credentials._plans import AuthorizedFill, NativePlan
from tests.test_browser_credential_lease import MemoryRedis, identity
from tests.test_browser_credential_native import ORIGIN, selection, snapshot
from tests.test_browser_credentials import PASSWORD, login

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.identity = identity()
        self.ctx = AuthContext(
            user_id=self.identity.user_id,
            organization_id=self.identity.organization_id,
            role="owner",
        )
        self.order: list[str] = []
        self.in_transaction = False
        self.observed = BrowserFillObservation(
            document_id=uuid4(),
            origin=ORIGIN,
            fields=(
                BrowserFillHandle(
                    field="password", handle=uuid4(), role="password", form_origin=ORIGIN
                ),
            ),
        )
        self.plan_id = uuid4()
        self.claim = AuthorizedFill(
            self.plan_id,
            uuid4(),
            self.identity.credential_ids[0],
            uuid4(),
            BrowserFillOperation.FILL,
            self.observed,
            login(),
        )
        self.service = SimpleNamespace(
            prepare=AsyncMock(),
            claim=AsyncMock(side_effect=self.claimed),
            authorize_effect=AsyncMock(side_effect=self.authorized),
            finish=AsyncMock(),
            refuse=AsyncMock(),
            pending=AsyncMock(return_value=None),
            request=AsyncMock(),
            get=AsyncMock(),
            submitted=AsyncMock(return_value=None),
        )
        self.native = SimpleNamespace(
            prepare=AsyncMock(return_value=self.observed),
            verify=AsyncMock(return_value=self.observed),
            verify_submission=AsyncMock(return_value=self.observed),
            fill=AsyncMock(side_effect=self.fill),
            submit=AsyncMock(side_effect=self.submit),
            close=AsyncMock(),
            origin=AsyncMock(return_value=ORIGIN),
        )
        self.page = SimpleNamespace(
            credentials=self.native, output_guard=BrowserOutputGuard(), inherited_credentials=()
        )
        self.events = []
        self.value_factories = 0
        self.effect_result = True
        self.writer = controller.BrowserCredentialController(
            self.identity,
            self.ctx,
            MemoryRedis(),
            self.page,
            asyncio.Lock(),
            snapshot,
            self.protect,
            self.sink,
        )
        self.writer.lease = SimpleNamespace(
            check=AsyncMock(), acquire=AsyncMock(), close=AsyncMock(), observe=AsyncMock()
        )
        monkeypatch.setattr(controller, "get_db_context", self.transaction)
        monkeypatch.setattr(
            controller, "BrowserCredentialPlanService", lambda db, redis: self.service
        )
        monkeypatch.setattr(controller, "POLL_SECONDS", 0)
        monkeypatch.setattr(controller, "require_private_transport", lambda: None)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[object]:
        assert not self.in_transaction
        self.in_transaction = True
        self.order.append("begin")
        try:
            yield object()
        finally:
            self.in_transaction = False
            self.order.append("commit")

    async def claimed(self, *args, **kwargs):
        assert self.page.output_guard.active and self.in_transaction
        assert kwargs["output_protected"] is True
        self.order.append("claim")
        return self.claim

    async def authorized(self, *args):
        assert self.order[-2:] == ["commit", "begin"]
        assert self.in_transaction
        self.order.append("authorize")

    async def protect(self, origin: str) -> None:
        assert not self.in_transaction
        self.order.append("protect")
        self.page.output_guard.protect(origin)

    async def sink(self, event) -> None:
        self.events.append(event)

    async def fill(self, values) -> bool:
        assert self.page.output_guard.active and self.in_transaction
        assert self.order[-1] == "authorize"
        self.value_factories += 1
        opened = values()
        assert [item.get_secret_value() for item in opened.items] == [PASSWORD]
        self.order.append("fill")
        return self.effect_result

    async def submit(self) -> bool:
        assert self.page.output_guard.active and self.in_transaction
        assert self.claim.value is None and self.order[-1] == "authorize"
        self.order.append("submit")
        return self.effect_result

    def plan(
        self, state=BrowserFillState.APPROVED, *, operation=BrowserFillOperation.FILL, parent=None
    ):
        return NativePlan(
            self.plan_id, state, operation, parent, selection("password"), self.observed
        )

    def read(self, state, *, operation=BrowserFillOperation.FILL):
        return BrowserCredentialPlanRead(
            id=self.plan_id,
            operation=operation,
            parent_plan_id=None,
            run_id=self.identity.run_id,
            call_id=self.identity.call_id,
            tab_id=self.identity.tab_id,
            secret_id=self.identity.credential_ids[0],
            authorization_generation=self.claim.generation,
            state=state,
            fields=["password"],
            origin=ORIGIN,
            document_id=self.observed.document_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            reason_code=None,
            output_protected=state in (BrowserFillState.FILLED, BrowserFillState.SUBMITTED),
        )

    def hold_alive(self) -> None:
        self.writer._task = asyncio.create_task(asyncio.Event().wait())


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


@pytest.mark.parametrize("success", [True, False])
async def test_fill_is_protected_claimed_committed_reauthorized_and_sent_once(
    harness: Harness,
    success: bool,
) -> None:
    h = harness
    h.effect_result = success
    await h.writer._step(h.plan(BrowserFillState.REQUESTED))
    assert h.writer._prepared == h.plan_id
    h.service.prepare.assert_awaited_once_with(h.ctx, h.identity, h.plan_id, h.observed)
    h.order.clear()
    await h.writer._step(h.plan())
    assert h.order == [
        "protect",
        "begin",
        "claim",
        "commit",
        "begin",
        "authorize",
        "fill",
        "commit",
    ]
    assert h.value_factories == 1
    h.service.finish.assert_awaited_once_with(h.identity, h.claim, filled=success)
    h.native.submit.assert_not_awaited()
    if not success:
        assert h.writer._prepared is None
        h.native.close.assert_awaited_once()
    else:
        assert h.writer._prepared == h.plan_id


async def test_submission_is_a_separate_explicit_plan_and_never_reopens_values(
    harness: Harness,
) -> None:
    h = harness
    parent = uuid4()
    h.writer._prepared = parent
    h.claim = AuthorizedFill(
        h.plan_id,
        uuid4(),
        h.claim.secret_id,
        h.claim.generation,
        BrowserFillOperation.SUBMIT,
        h.observed,
        None,
    )
    await h.writer._step(h.plan(operation=BrowserFillOperation.SUBMIT, parent=parent))
    assert "submit" in h.order and "fill" not in h.order
    h.native.verify_submission.assert_awaited_once()
    h.native.fill.assert_not_awaited()
    h.native.close.assert_awaited_once()
    assert h.writer._prepared is None and h.value_factories == 0


@pytest.mark.parametrize(
    "failure", ["no_snapshot", "wrong_prepared", "document_change", "protection", "authority"]
)
async def test_pre_effect_refusals_do_not_send_values(harness: Harness, failure: str) -> None:
    h = harness
    h.writer._prepared = h.plan_id
    plan = h.plan()
    if failure == "no_snapshot":
        h.writer.snapshot = lambda: None
        plan = h.plan(BrowserFillState.REQUESTED)
    elif failure == "wrong_prepared":
        h.writer._prepared = uuid4()
    elif failure == "document_change":
        h.native.verify.return_value = h.observed.model_copy(update={"document_id": uuid4()})
    elif failure == "protection":
        h.writer.protect = AsyncMock(
            side_effect=BrowserFillRefused(BrowserFillReason.PROTECTION_UNAVAILABLE)
        )
    else:
        h.service.authorize_effect.side_effect = BrowserFillRefused(
            BrowserFillReason.AUTHORITY_CHANGED
        )
    with pytest.raises(BrowserFillRefused):
        await h.writer._step(plan)
    h.native.fill.assert_not_awaited()
    h.native.submit.assert_not_awaited()


async def test_waiting_confirmation_verifies_but_never_claims_or_fills(harness: Harness) -> None:
    h = harness
    h.writer._prepared = h.plan_id
    await h.writer._step(h.plan(BrowserFillState.AWAITING_CONFIRMATION))
    h.native.verify.assert_awaited_once()
    h.service.claim.assert_not_awaited()
    assert not h.page.output_guard.active


@pytest.mark.parametrize(
    "error",
    [
        BrowserFillRefused(BrowserFillReason.DOCUMENT_CHANGED),
        RuntimeError("synthetic private transport details"),
    ],
)
async def test_run_failure_retains_fixed_receipt_and_closes_lease_and_native_handle(
    harness: Harness,
    error: Exception,
) -> None:
    h = harness
    h.writer._prepared = h.plan_id
    h.service.pending.return_value = h.plan()
    h.native.verify.side_effect = error
    h.writer.lease.check.side_effect = [None, BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)]
    await h.writer._run()
    h.service.refuse.assert_awaited()
    for call in h.service.refuse.await_args_list:
        assert isinstance(call.args[2], BrowserFillReason)
    h.native.fill.assert_not_awaited()
    h.native.close.assert_awaited()
    h.writer.lease.close.assert_awaited_once()
    assert h.writer._closed and not h.writer.alive


async def test_cancellation_during_effect_stays_protected_and_records_uncertainty_once(
    harness: Harness,
) -> None:
    h = harness
    started = asyncio.Event()

    async def blocked(values):
        started.set()
        await asyncio.Event().wait()

    h.writer._prepared = h.plan_id
    h.service.pending.return_value = h.plan()
    h.native.fill.side_effect = blocked
    h.writer._task = asyncio.create_task(h.writer._run())
    await started.wait()
    await h.writer.close()
    assert h.page.output_guard.active
    h.native.fill.assert_awaited_once()
    h.service.refuse.assert_awaited_once_with(
        h.identity, h.plan_id, BrowserFillReason.OWNERSHIP_LOST, output_protected=True
    )
    h.native.close.assert_awaited()
    h.writer.lease.close.assert_awaited()
    h.service.finish.assert_not_awaited()


async def test_idle_close_and_absent_plan_do_not_create_a_receipt(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness
    monkeypatch.setattr(controller, "IDLE_SECONDS", 0)
    await h.writer._run()
    await h.writer._receipt(BrowserFillReason.OWNERSHIP_LOST)
    h.service.refuse.assert_not_awaited()
    await h.writer.close()
    assert h.writer._closed


async def test_empty_poll_is_bounded_and_observes_only_origin(harness: Harness) -> None:
    h = harness
    h.writer.lease.check.side_effect = [None, BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)]
    await h.writer._run()
    h.writer.lease.observe.assert_awaited_once_with(ORIGIN)
    h.service.pending.assert_awaited_once()
    h.service.refuse.assert_not_awaited()


async def test_an_unreadable_origin_is_not_published_and_does_not_keep_the_loop_unbounded(
    harness: Harness,
) -> None:
    h = harness
    h.native.origin.return_value = ""
    h.writer.lease.check.side_effect = [None, BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)]
    await h.writer._run()
    h.writer.lease.observe.assert_not_awaited()


async def test_request_keeps_only_reference_fields_and_requires_live_owner(
    harness: Harness,
) -> None:
    h = harness
    with pytest.raises(BrowserFillRefused):
        await h.writer.request(h.claim.secret_id, h.claim.generation, selection("password"))
    h.hold_alive()
    try:
        h.service.request.return_value = h.read(BrowserFillState.REQUESTED)
        await h.writer.request(h.claim.secret_id, h.claim.generation, selection("password"))
        request = h.service.request.await_args.args[2]
        assert (
            request.secret_id == h.claim.secret_id
            and request.fields == selection("password").fields
        )
        assert PASSWORD not in request.model_dump_json()
    finally:
        await h.writer.close()


async def test_wait_notifies_once_per_separate_decision_and_only_reports_fixed_status(
    harness: Harness,
) -> None:
    h = harness
    h.hold_alive()
    h.service.get.side_effect = [
        h.read(BrowserFillState.AWAITING_CONFIRMATION),
        h.read(BrowserFillState.AWAITING_CONFIRMATION),
        h.read(BrowserFillState.FILLED),
        h.read(BrowserFillState.FILLED),
    ]
    h.service.submitted.side_effect = [
        None,
        h.read(BrowserFillState.SUBMITTED, operation=BrowserFillOperation.SUBMIT),
    ]
    try:
        result = await h.writer.wait(h.plan_id)
        assert "submitted" in result and "hidden" in result
        assert [event.credential_operation for event in h.events] == ["fill", "submit"]
        assert all(
            event.credential_plan_id == str(h.plan_id) and event.image is None for event in h.events
        )
    finally:
        await h.writer.close()


@pytest.mark.parametrize(
    "state", [BrowserFillState.REFUSED, BrowserFillState.EXPIRED, BrowserFillState.UNKNOWN]
)
async def test_wait_returns_terminal_receipt_without_retry(harness: Harness, state) -> None:
    h = harness
    h.hold_alive()
    h.service.get.return_value = h.read(state)
    try:
        assert state.value in await h.writer.wait(h.plan_id)
        h.service.request.assert_not_awaited()
    finally:
        await h.writer.close()


async def test_wait_ends_when_owner_is_not_alive(harness: Harness) -> None:
    assert "ended" in await harness.writer.wait(harness.plan_id)
    harness.service.get.assert_not_awaited()


def admitted_deps(h: Harness):
    return SimpleNamespace(
        organization_id=h.identity.organization_id,
        run_id=h.identity.run_id,
        agent_id=h.identity.agent_id,
        user_id=str(h.identity.user_id),
        run_person=h.identity.user_id,
        impersonated=False,
        delegated=False,
        audience=SimpleNamespace(
            user_id=h.identity.user_id, browses_signed_in=True, shared_transcript=False
        ),
    )


async def create(h: Harness, deps):
    return await controller.BrowserCredentialController.create(
        deps=deps,
        credential_ids=h.identity.credential_ids,
        tab_id="main",
        call_id="call",
        redis=MemoryRedis(),
        page=h.page,
        tab_lock=asyncio.Lock(),
        snapshot=snapshot,
        protect=h.protect,
        sink=h.sink,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", None),
        ("run_id", None),
        ("agent_id", None),
        ("impersonated", True),
        ("delegated", True),
        ("audience", None),
        ("run_person", None),
        ("user_id", "another"),
        ("audience.browses_signed_in", False),
        ("audience.shared_transcript", True),
        ("audience.user_id", None),
    ],
)
async def test_controller_admission_never_opens_a_nonpersonal_browser(
    harness, field, value
) -> None:
    h = harness
    deps = admitted_deps(h)
    target, attribute = (
        (deps.audience, field.split(".")[1]) if field.startswith("audience.") else (deps, field)
    )
    setattr(target, attribute, value)
    assert await create(h, deps) is None
    h.native.origin.assert_not_awaited()


async def test_controller_admission_empty_binding_and_disabled_deployment_refuse(
    harness, monkeypatch
) -> None:
    h = harness
    h.identity = h.identity.model_copy(update={"credential_ids": ()})
    assert await create(h, admitted_deps(h)) is None
    h.identity = identity()
    monkeypatch.setattr(
        controller._access,
        "enabled",
        lambda *args: (_ for _ in ()).throw(BrowserFillRefused(BrowserFillReason.DISABLED)),
    )
    assert await create(h, admitted_deps(h)) is None


@pytest.mark.parametrize(
    "case",
    ["member_removed", "lease_refused", "origin_refused", "cancelled", "empty_origin", "created"],
)
async def test_controller_startup_is_bounded_and_cleanup_covers_cancel_before_first_task_turn(
    harness,
    monkeypatch,
    case,
) -> None:
    h = harness
    monkeypatch.setattr(controller._access, "enabled", lambda *args: None)
    monkeypatch.setattr(
        controller,
        "member_context",
        AsyncMock(return_value=None if case == "member_removed" else h.ctx),
    )
    monkeypatch.setattr(
        controller._access, "private_run", AsyncMock(return_value=(h.ctx, object()))
    )
    monkeypatch.setattr(controller, "BrowserWriterLease", lambda *args: h.writer.lease)
    if case == "lease_refused":
        h.writer.lease.acquire.side_effect = BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)
    elif case == "origin_refused":
        h.native.origin.side_effect = BrowserFillRefused(BrowserFillReason.PROVIDER_UNAVAILABLE)
    elif case == "cancelled":
        h.native.origin.side_effect = asyncio.CancelledError
    elif case == "empty_origin":
        h.native.origin.return_value = ""
    if case == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await create(h, admitted_deps(h))
    else:
        result = await create(h, admitted_deps(h))
        if case in {"created", "empty_origin"}:
            assert result.alive
            # No scheduling yield before close: the task's own finally never ran.
            await result.close()
            assert not result.alive
            h.native.close.assert_awaited_once()
        else:
            assert result is None
    if case != "member_removed":
        h.writer.lease.close.assert_awaited()
    if case == "empty_origin":
        h.writer.lease.observe.assert_not_awaited()
