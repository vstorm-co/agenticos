"""Evaluation locks must not reuse namespaces already deployed on main."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.locks import LockScope, hold_subject, try_hold_subject

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("evaluation_scope", "platform_scope"),
    [
        (LockScope.REVIEW_PER_CASE, LockScope.COLLECTION_DDL),
        (LockScope.EVAL_CASES_PER_ORGANIZATION, LockScope.CONVERSATION_FORK_STORAGE_PER_ORG),
    ],
)
async def test_evaluation_and_platform_locks_remain_independent(
    engine: AsyncEngine, evaluation_scope: LockScope, platform_scope: LockScope
) -> None:
    sessions = async_sessionmaker(engine)
    subject = uuid4()
    async with sessions() as evaluation, sessions() as platform:
        await hold_subject(evaluation, evaluation_scope, subject)
        assert await try_hold_subject(platform, platform_scope, subject)
