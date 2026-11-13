"""A coding task's change set is read with its conversation's access, and goes with it (#2480).

Against a real `ConversationService` and a real database, because the guarantee
is the conversation's own reader check and the cascade - neither of which a mock
can show.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.agents.capabilities.coding_agent import _changes, _toolset
from app.agents.capabilities.coding_agent._harness import CodingReport
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.coding_task_change import CodingTaskChange
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import conversation_share as conversation_share_repo
from app.schemas.coding_task_change import ChangedFile, ChangeSet
from app.services import coding_task_changes as change_service_module
from app.services.coding_task_changes import CodingTaskChangeService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _person(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _organization(db: AsyncSession, *members: User) -> Organization:
    founder = await _person(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    for member in members:
        db.add(
            OrganizationMember(id=uuid.uuid4(), organization_id=organization.id, user_id=member.id)
        )
    await db.flush()
    return organization


def _as(user: User, organization: Organization) -> AuthContext:
    return AuthContext(user_id=user.id, organization_id=organization.id, role="member")


async def _recorded(db: AsyncSession, organization: Organization, owner: User) -> CodingTaskChange:
    conversation = Conversation(
        id=uuid.uuid4(), user_id=owner.id, organization_id=organization.id, title="Fix it"
    )
    db.add(conversation)
    await db.flush()
    changes = ChangeSet(
        files=[
            ChangedFile(
                path="src/app.py",
                status="modified",
                additions=1,
                deletions=1,
                patch="diff --git a/src/app.py b/src/app.py\n-a - b\n+a + b\n",
            ),
            ChangedFile(path="README.md", status="added", additions=1, patch="+# Demo\n"),
        ]
    )
    return await CodingTaskChangeService(db).record(
        changes,
        organization_id=organization.id,
        conversation_id=conversation.id,
        tool_call_id="call-1",
        harness="claude_code",
    )


async def test_the_conversations_owner_reads_exactly_the_files_recorded(db: AsyncSession) -> None:
    owner = await _person(db)
    organization = await _organization(db, owner)
    recorded = await _recorded(db, organization, owner)

    change = await CodingTaskChangeService(db).get(_as(owner, organization), recorded.id)

    assert [entry["path"] for entry in change.files] == ["src/app.py", "README.md"]
    assert change.files[0]["patch"].endswith("+a + b\n")
    assert repr(change).startswith("<CodingTaskChange(id=")


async def test_a_colleague_who_may_not_read_the_conversation_reads_none(
    db: AsyncSession,
) -> None:
    owner, colleague = await _person(db), await _person(db)
    organization = await _organization(db, owner, colleague)
    recorded = await _recorded(db, organization, owner)

    with pytest.raises(NotFoundError):
        await CodingTaskChangeService(db).get(_as(colleague, organization), recorded.id)


async def test_somebody_the_conversation_was_shared_with_reads_it_too(
    db: AsyncSession,
) -> None:
    """Whoever may read the transcript sees the diff under it, not only its owner."""
    owner, colleague = await _person(db), await _person(db)
    organization = await _organization(db, owner, colleague)
    recorded = await _recorded(db, organization, owner)
    await conversation_share_repo.create(
        db, conversation_id=recorded.conversation_id, shared_by=owner.id, shared_with=colleague.id
    )

    change = await CodingTaskChangeService(db).get(_as(colleague, organization), recorded.id)

    assert change.id == recorded.id


async def test_somebody_in_another_organization_reads_none(db: AsyncSession) -> None:
    owner, stranger = await _person(db), await _person(db)
    organization = await _organization(db, owner)
    elsewhere = await _organization(db, stranger)
    recorded = await _recorded(db, organization, owner)

    with pytest.raises(NotFoundError):
        await CodingTaskChangeService(db).get(_as(stranger, elsewhere), recorded.id)
    # Not even by naming the organization it is in.
    with pytest.raises(NotFoundError):
        await CodingTaskChangeService(db).get(_as(stranger, organization), recorded.id)


async def test_deleting_the_conversation_deletes_its_change_sets(db: AsyncSession) -> None:
    owner = await _person(db)
    organization = await _organization(db, owner)
    recorded = await _recorded(db, organization, owner)
    conversation = await db.get(Conversation, recorded.conversation_id)

    await db.delete(conversation)
    await db.flush()
    db.expunge_all()

    remaining = await db.execute(select(CodingTaskChange).where(CodingTaskChange.id == recorded.id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.parametrize("share", ["view", "edit"])
async def test_only_an_edit_share_can_restore_a_task_and_the_result_is_recorded(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, share: str
) -> None:
    from app.db.models.audit_log import AppAdminAuditLog

    owner, colleague = await _person(db), await _person(db)
    organization = await _organization(db, owner, colleague)
    recorded = await _recorded(db, organization, owner)
    recorded.revert_patch = "cGF0Y2g="
    recorded.workspace_ref = {"provider": "sandboxd:example", "id": "original"}
    await db.flush()
    await conversation_share_repo.create(
        db,
        conversation_id=recorded.conversation_id,
        shared_by=owner.id,
        shared_with=colleague.id,
        permission=share,
    )

    @asynccontextmanager
    async def opened(*args: object, **kwargs: object) -> AsyncGenerator[object]:
        yield SimpleNamespace()

    monkeypatch.setattr(change_service_module.SandboxWorkspaceService, "open_recorded", opened)
    restore = AsyncMock()
    monkeypatch.setattr(change_service_module._coding_task_revert, "revert", restore)
    ctx = AuthContext(user_id=colleague.id, organization_id=organization.id, role="viewer")
    if share == "view":
        with pytest.raises(NotFoundError):
            await CodingTaskChangeService(db).revert(ctx, recorded.id)
        restore.assert_not_awaited()
        assert recorded.reverted_at is None
    else:
        result = await CodingTaskChangeService(db).revert(ctx, recorded.id)
        assert result.reverted_at is not None
        await db.refresh(recorded)
        assert recorded.reverted_at == result.reverted_at
        audit = await db.scalar(
            select(AppAdminAuditLog).where(AppAdminAuditLog.target_id == str(recorded.id))
        )
        assert audit is not None and audit.actor_user_id == colleague.id
        assert audit.action == "coding_task.revert"
        assert audit.details == {"conversation_id": str(recorded.conversation_id), "file_count": 2}


async def test_a_change_set_that_cannot_be_kept_leaves_its_code_out_of_the_logs(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A conversation gone mid-task fails the insert on a foreign key - here both
    parents are made up - and the error's text carries the INSERT's parameters.

    Through the application's own `get_db_context`, which the `engine` fixture
    points at this suite's database and disposes first.
    """
    secret = "OPENAI_API_KEY=sk-live-do-not-log"
    changes = ChangeSet(
        files=[ChangedFile(path=".env", status="added", additions=1, patch=f"+{secret}\n")]
    )

    async def finished(*_: object) -> ChangeSet:
        return changes

    monkeypatch.setattr(_toolset._changes, "finish", finished)
    ctx = SimpleNamespace(
        deps=SimpleNamespace(organization_id=uuid.uuid4(), conversation_id=uuid.uuid4()),
        tool_call_id="call-1",
        workspace=SimpleNamespace(ref=None),
    )
    report = CodingReport(harness="claude_code", access="edit", outcome="completed", answer="Done")

    kept = await _toolset._with_changes(
        cast(Any, ctx),
        report,
        _changes.Baseline(store="/tmp/x", tree="a" * 40),  # noqa: S108
    )

    assert kept.changes_id is None
    assert "could not be recorded: IntegrityError" in caplog.text
    assert secret not in caplog.text
