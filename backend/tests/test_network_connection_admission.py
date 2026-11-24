"""Admission never waits under teardown locks or resumes a removed membership."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import ConcurrentChangeError, NotFoundError
from app.db.locks import LockScope
from app.services.network_connections import admission

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def env(monkeypatch):
    db = MagicMock()
    events = []

    @asynccontextmanager
    async def savepoint():
        events.append("savepoint")
        try:
            yield
        except BaseException:
            events.append("rollback")
            raise
        else:
            events.append("release")

    db.begin_nested.side_effect = savepoint
    subject = AsyncMock(return_value=True)
    parent = AsyncMock(return_value=True)
    quota = AsyncMock(return_value=True)
    monkeypatch.setattr(admission, "try_hold_subject", subject)
    monkeypatch.setattr(admission.network_connection_repo, "lock_parent", parent)
    monkeypatch.setattr(admission.network_connection_repo, "lock_quota", quota)
    return db, events, subject, parent, quota


async def test_parent_contention_rolls_back_its_savepoint_before_becoming_a_retry(env):
    db, events, _, parent, _ = env
    original = Exception("synthetic lock contention")
    original.sqlstate = "55P03"
    parent.side_effect = DBAPIError("SELECT", {}, original)
    with pytest.raises(ConcurrentChangeError):
        await admission.hold_parent(db, uuid4())
    assert events == ["savepoint", "rollback"]


async def test_unrelated_database_failure_is_not_mislabeled_as_a_busy_organization(env):
    db, events, _, parent, _ = env
    parent.side_effect = DBAPIError("SELECT", {}, Exception("synthetic db failure"))
    with pytest.raises(DBAPIError):
        await admission.hold_parent(db, uuid4())
    assert events[-1] == "rollback"


async def test_missing_parent_cannot_admit_new_network_work(env):
    db, _, _, parent, _ = env
    parent.return_value = False
    with pytest.raises(NotFoundError):
        await admission.hold_parent(db, uuid4())


async def test_busy_account_never_takes_an_organization_or_connection_lock(env):
    db, _, subject, parent, quota = env
    subject.return_value = False
    with pytest.raises(ConcurrentChangeError):
        await admission.guard_member(db, organization_id=uuid4(), user_id=uuid4(), admission=True)
    parent.assert_not_awaited()
    quota.assert_not_awaited()


async def test_admission_and_cleanup_share_the_account_erasure_fence(env):
    db, events, subject, parent, quota = env
    org, user = uuid4(), uuid4()
    await admission.guard_member(db, organization_id=org, user_id=user, admission=True)
    subject.assert_awaited_once_with(db, LockScope.PERSONAL_DATA_PER_USER, user)
    quota.assert_awaited_once_with(db, organization_id=org)
    parent.assert_not_awaited()
    assert events == []
    await admission.guard_member(db, organization_id=org, user_id=user)
    assert subject.await_count == 2
    parent.assert_awaited_once_with(db, organization_id=org)
    assert events == ["savepoint", "release"]


async def test_missing_org_quota_lock_refuses_admission(env):
    db, _, _, _, quota = env
    quota.return_value = False
    with pytest.raises(NotFoundError):
        await admission.guard_member(db, organization_id=uuid4(), user_id=uuid4(), admission=True)
