"""Client request IDs cannot escape tenant scope through a global database constraint."""

import inspect
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.browser_continuation import (
    BrowserContinuationReason,
    BrowserContinuationRefused,
    BrowserContinuationState,
)
from app.core.config import settings
from app.db.models.browser_credential_continuation import BrowserCredentialContinuation
from app.db.models.browser_sign_in import BrowserSignIn
from app.repositories import browser_credential_continuation as repo
from tests.integration.test_browser_credential_continuations import continuation as continuation
from tests.integration.test_browser_credential_continuations import submitted
from tests.integration.test_browser_credential_plans import browser as browser

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
async def other_browser(db, monkeypatch):
    """Reuse the native setup for an independent tenant without duplicating it."""
    with monkeypatch.context() as scoped:
        async with asynccontextmanager(inspect.unwrap(browser))(db, scoped) as other:
            yield other


async def test_cross_organization_request_id_collision_is_closed_and_keeps_transaction_usable(
    browser, other_browser, monkeypatch
):
    left, right = browser, other_browser
    assert left.org.id != right.org.id and left.owner.id != right.owner.id
    monkeypatch.setattr(
        settings, "BROWSER_CREDENTIAL_ORGANIZATION_IDS", [left.org.id, right.org.id]
    )
    first = await submitted(left)
    existing = await first.request()
    # Start the second request without a foreign receipt in its ORM identity map.
    # The conflicting primary key is already durable in PostgreSQL.
    left.db.expunge(await repo.get(left.db, left.org.id, existing.id))
    await left.db.commit()
    second = await submitted(right)
    with pytest.raises(BrowserContinuationRefused) as refused:
        await second.request(existing.id)
    assert refused.value.reason == BrowserContinuationReason.ALREADY_CONSUMED
    assert all(
        str(value) not in str(refused.value)
        for value in (left.org.id, left.owner.id, left.secret.id, existing.id)
    )
    # The outer transaction is still usable, but no cross-tenant lookup or new
    # receipt/effect has been manufactured by the failed request.
    assert await repo.get(right.db, right.org.id, existing.id) is None
    assert await repo.for_submission(right.db, right.org.id, second.submission_id) is None
    assert (
        await right.db.scalar(select(func.count()).select_from(BrowserCredentialContinuation)) == 1
    )
    assert await right.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0
    assert await first.service.get(left.ctx, left.run.id, first.submission_id) == existing
    fresh = await second.request()
    assert fresh.id != existing.id and fresh.state == BrowserContinuationState.REQUESTED
    stored = await repo.get(right.db, right.org.id, fresh.id)
    assert stored.attempt_id is None and stored.saved_sign_in_id is None


@pytest.mark.parametrize("violation", ["protected_check", "active_view_unique"])
async def test_unrelated_native_integrity_failures_are_not_mislabeled_as_request_replays(
    continuation, monkeypatch, violation
):
    first, b = continuation, continuation.browser
    second = await submitted(b)
    real_create = repo.create

    async def violate(db, row):
        if violation == "protected_check":
            row.output_protected = False
        else:
            # A native competing active-view insert after admission is not an ID
            # or source replay. Its unexpected constraint failure must remain visible.
            values = {
                column.name: getattr(row, column.name)
                for column in row.__table__.columns
                if column.name not in ("created_at", "updated_at")
            }
            competing = BrowserCredentialContinuation(
                **(
                    values
                    | {
                        "id": uuid4(),
                        "source_submission_id": first.submission_id,
                        "source_fill_id": first.fill_id,
                    }
                )
            )
            await real_create(db, competing)
        return await real_create(db, row)

    monkeypatch.setattr(repo, "create", violate)
    with pytest.raises(IntegrityError) as caught:
        await second.request()
    assert caught.value.orig.sqlstate == ("23514" if violation == "protected_check" else "23505")
    if violation == "active_view_unique":
        assert caught.value.orig.__cause__.constraint_name == "uq_browser_continuations_active_view"
    # Savepoint rollback preserves the caller's transaction, including on an
    # unrelated failure, without retaining either attempted receipt or an effect.
    assert await b.db.scalar(select(func.count()).select_from(BrowserCredentialContinuation)) == 0
    assert await b.db.scalar(select(func.count()).select_from(BrowserSignIn)) == 0
