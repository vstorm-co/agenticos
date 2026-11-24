"""The durable claim precedes native export; every failed publication closes only its new view."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.browser_continuation import (
    BrowserContinuationObservation,
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.browser_fill import (
    BrowserFillOperation,
    BrowserFillReason,
    BrowserFillRefused,
    BrowserFillState,
)
from app.core.browser_session import ProtectedSignIn, bounded_cookies
from app.services.browser_credentials import _controller as controller
from app.services.browser_credentials._continuation import ContinuationClaim, NativeContinuation
from tests.test_browser_credential_controller import Harness
from tests.test_browser_credential_native import ORIGIN
from tests.test_browser_session import PRIVATE, provenance, raw_cookie

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class ContinuationHarness:
    def __init__(self, monkeypatch):
        self.base = Harness(monkeypatch)
        self.writer = self.base.writer
        self.writer.page.output_guard.protect(ORIGIN)
        self.order = []
        self.in_transaction = False
        self.transaction_count = 0
        self.failure = None
        self.cancel = False
        self.plan_id = uuid4()
        self.seen = BrowserContinuationObservation(document_id=uuid4(), origin=ORIGIN)
        self.claim = ContinuationClaim(
            self.plan_id,
            uuid4(),
            self.seen,
            provenance(
                organization_id=self.base.identity.organization_id,
                user_id=self.base.identity.user_id,
                agent_id=self.base.identity.agent_id,
                continuation_id=self.plan_id,
                origin=ORIGIN,
            ),
            True,
            str(uuid4()),
            str(uuid4()),
        )
        from urllib.parse import urlsplit

        self.cookies = bounded_cookies(
            ORIGIN, [raw_cookie(domain=urlsplit(ORIGIN).hostname)], now=20
        )
        self.native = SimpleNamespace(
            prepare=AsyncMock(return_value=self.seen),
            verify=AsyncMock(return_value=self.seen),
            export=AsyncMock(side_effect=self.export),
            close=AsyncMock(side_effect=lambda: self.order.append("close_handle")),
        )
        self.writer.page.continuation = self.native
        self.writer.continue_session = self.open
        self.service = SimpleNamespace(
            prepare=AsyncMock(),
            claim=AsyncMock(side_effect=self.claimed),
            authorize_effect=AsyncMock(side_effect=self.authorize),
            finish=AsyncMock(side_effect=self.finish),
            refuse=AsyncMock(),
            pending=AsyncMock(),
            get=AsyncMock(),
        )
        monkeypatch.setattr(controller, "get_db_context", self.transaction)
        monkeypatch.setattr(
            controller, "BrowserCredentialContinuationService", lambda db, redis: self.service
        )

    def plan(self, state=BrowserContinuationState.APPROVED):
        return NativeContinuation(self.plan_id, state, self.seen)

    def fail(self, stage):
        if self.failure == stage:
            if self.cancel:
                raise asyncio.CancelledError
            raise RuntimeError(PRIVATE)

    @asynccontextmanager
    async def transaction(self):
        assert not self.in_transaction
        self.transaction_count += 1
        self.in_transaction = True
        self.order.append("begin")
        try:
            yield object()
            if self.transaction_count == 2:
                self.fail("commit")
        except BaseException:
            self.order.append("rollback")
            raise
        else:
            self.order.append("commit")
        finally:
            self.in_transaction = False

    async def claimed(self, *args):
        assert self.in_transaction and self.writer.page.output_guard.active
        self.order.append("claim")
        return self.claim

    async def authorize(self, *args):
        assert self.order[-2:] == ["commit", "begin"]
        self.order.append("authorize")
        self.fail("authority")

    async def export(self, *, now):
        assert self.in_transaction and self.order[-1] == "authorize"
        self.order.append("export")
        self.fail("export")
        return self.cookies

    @asynccontextmanager
    async def open(self, claim, state):
        assert self.in_transaction and self.writer.page.output_guard.active
        assert state == ProtectedSignIn(provenance=claim.provenance, cookies=self.cookies)
        self.order.append("open_owned")
        try:
            self.fail("open")
            yield
        except BaseException:
            self.order.append("close_owned")
            raise
        else:
            self.order.append("retain_owned")

    async def finish(self, *args):
        assert self.in_transaction and self.order[-1] == "open_owned"
        self.order.append("finish")
        self.fail("finish")


@pytest.fixture
def continuation(monkeypatch):
    return ContinuationHarness(monkeypatch)


async def test_preparation_and_pending_consent_never_export_save_or_open(continuation):
    h = continuation
    await h.writer._step_continuation(h.plan(BrowserContinuationState.REQUESTED))
    assert h.writer._continuation_prepared == h.plan_id
    h.service.prepare.assert_awaited_once_with(h.base.ctx, h.base.identity, h.plan_id, h.seen)
    await h.writer._step_continuation(h.plan(BrowserContinuationState.AWAITING_CONFIRMATION))
    h.native.export.assert_not_awaited()
    h.service.claim.assert_not_awaited()
    h.service.finish.assert_not_awaited()
    assert "open_owned" not in h.order


async def test_claim_is_committed_before_export_and_publication_commit_before_context_survives(
    continuation,
):
    h = continuation
    h.writer._continuation_prepared = h.plan_id
    await h.writer._step_continuation(h.plan())
    assert h.order == [
        "begin",
        "claim",
        "commit",
        "begin",
        "authorize",
        "export",
        "open_owned",
        "finish",
        "commit",
        "retain_owned",
        "close_handle",
    ]
    h.native.export.assert_awaited_once()
    assert h.writer._continuation_prepared is None
    assert h.writer.page.output_guard.active


@pytest.mark.parametrize("stage", ["authority", "export", "open", "finish", "commit"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_publication_reaps_new_context_and_never_repeats_export(
    continuation, stage, cancel
):
    h = continuation
    h.failure, h.cancel = stage, cancel
    h.writer._continuation_prepared = h.plan_id
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await h.writer._step_continuation(h.plan())
    assert h.order[:3] == ["begin", "claim", "commit"]
    assert "rollback" in h.order and "retain_owned" not in h.order
    assert h.native.export.await_count == (0 if stage == "authority" else 1)
    assert ("close_owned" in h.order) is (stage in ("open", "finish", "commit"))
    assert h.writer.page.output_guard.active
    # Recovery is a durable fixed receipt, never another native export/open.
    h.failure = None
    await h.writer._continuation_receipt(BrowserContinuationReason.UNCERTAIN_EFFECT)
    h.service.refuse.assert_awaited_once_with(
        h.base.identity, h.plan_id, BrowserContinuationReason.UNCERTAIN_EFFECT
    )
    assert h.native.export.await_count <= 1


@pytest.mark.parametrize("mutation", ["missing_handle", "different_document", "missing_opener"])
async def test_unpinned_native_state_refuses_before_claim_or_export(continuation, mutation):
    h = continuation
    if mutation != "missing_handle":
        h.writer._continuation_prepared = h.plan_id
    if mutation == "different_document":
        h.native.verify.return_value = h.seen.model_copy(update={"document_id": uuid4()})
    elif mutation == "missing_opener":
        h.writer.continue_session = None
    with pytest.raises(BrowserContinuationRefused):
        await h.writer._step_continuation(h.plan())
    h.native.export.assert_not_awaited()
    h.service.claim.assert_not_awaited()


async def test_poll_refusal_settles_and_releases_only_native_observation(continuation):
    h = continuation
    h.writer._continuation_prepared = h.plan_id
    h.service.pending.return_value = h.plan()
    h.native.verify.side_effect = BrowserContinuationRefused(
        BrowserContinuationReason.DOCUMENT_CHANGED
    )
    await h.writer._poll_continuation()
    h.service.refuse.assert_awaited_once_with(
        h.base.identity, h.plan_id, BrowserContinuationReason.DOCUMENT_CHANGED
    )
    h.native.close.assert_awaited_once()
    assert h.writer._continuation_prepared is None and h.writer._continuation_active is None
    h.native.export.assert_not_awaited()


async def test_poll_without_work_does_not_touch_native_session(continuation):
    h = continuation
    h.service.pending.return_value = None
    await h.writer._poll_continuation()
    h.native.prepare.assert_not_awaited()
    h.native.verify.assert_not_awaited()
    h.native.export.assert_not_awaited()


async def test_writer_polls_continuations_only_after_no_fill_and_closes_both_native_handles(
    continuation,
):
    h = continuation
    h.service.pending.return_value = None
    h.writer.lease.check.side_effect = [None, BrowserFillRefused(BrowserFillReason.OWNERSHIP_LOST)]
    await h.writer._run()
    h.base.service.pending.assert_awaited_once()
    h.service.pending.assert_awaited_once_with(h.base.ctx, h.base.identity)
    h.native.close.assert_awaited_once()
    h.base.native.close.assert_awaited_once()
    h.writer.lease.close.assert_awaited_once()
    h.native.export.assert_not_awaited()
    assert h.writer._closed and h.writer.page.output_guard.active


@pytest.mark.parametrize(
    "terminal", [BrowserContinuationState.CONTINUED, BrowserContinuationState.UNKNOWN]
)
async def test_wait_recovers_by_get_without_repeating_submit_or_continuation_effects(
    continuation, terminal
):
    h = continuation
    h.base.hold_alive()
    h.base.service.get.return_value = h.base.read(BrowserFillState.FILLED)
    submission = h.base.read(BrowserFillState.SUBMITTED, operation=BrowserFillOperation.SUBMIT)
    h.base.service.submitted.return_value = submission
    protected_tab = str(uuid4()) if terminal == BrowserContinuationState.CONTINUED else None
    h.service.get.side_effect = [
        None,
        SimpleNamespace(state=BrowserContinuationState.AWAITING_CONFIRMATION),
        SimpleNamespace(state=terminal, continuation_tab_id=protected_tab),
    ]
    try:
        result = await h.writer.wait(h.base.plan_id)
        assert terminal.value in result and "Page output remains hidden" in result
        assert "authentication was not inferred" in result
        assert (protected_tab or "unavailable") in result
        assert PRIVATE not in result
        assert h.service.get.await_count == 3
        assert all(
            call.args == (h.base.ctx, h.base.identity.run_id, submission.id)
            for call in h.service.get.await_args_list
        )
        assert [event.credential_operation for event in h.base.events] == ["submit"]
        h.base.native.submit.assert_not_awaited()
        h.native.export.assert_not_awaited()
        h.service.prepare.assert_not_awaited()
        h.service.claim.assert_not_awaited()
    finally:
        await h.writer.close()
    h.native.close.assert_awaited_once()
    assert h.writer.page.output_guard.active
