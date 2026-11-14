"""A coding task's change set is read with its conversation's access, and goes with it (#2480).

Against a real `ConversationService` and a real database, because the guarantee
is the conversation's own reader check and the cascade - neither of which a mock
can show.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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
from app.services.sandbox_workspace import SandboxWorkspaceService

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
                before_blob="a" * 40,
                after_blob="b" * 40,
                before_mode="100644",
                after_mode="100644",
            ),
            ChangedFile(
                path="README.md",
                status="added",
                additions=1,
                patch="+# Demo\n",
                before_blob="0" * 40,
                after_blob="c" * 40,
                before_mode="000000",
                after_mode="100644",
            ),
        ]
    )
    return await CodingTaskChangeService(db).record(
        changes,
        organization_id=organization.id,
        conversation_id=conversation.id,
        tool_call_id="call-1",
        harness="claude_code",
        snapshot_isolated=True,
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
    from app.db.models.background_job import BackgroundJob

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

    workspace = AsyncMock(return_value=[])
    monkeypatch.setattr(
        change_service_module.SandboxWorkspaceService, "recorded_for_task", workspace
    )
    ctx = AuthContext(user_id=colleague.id, organization_id=organization.id, role="viewer")
    if share == "view":
        with pytest.raises(NotFoundError):
            await CodingTaskChangeService(db).revert(ctx, recorded.id)
        workspace.assert_not_awaited()
        assert recorded.reverted_at is None
    else:
        result = await CodingTaskChangeService(db).revert(ctx, recorded.id)
        assert result.reverted_at is None and result.revert_status == "pending"
        await db.refresh(recorded)
        job = await db.get(BackgroundJob, recorded.revert_job_id)
        assert job is not None and job.payload["user_id"] == str(colleague.id)
        assert job.payload["organization_id"] == str(organization.id)


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


async def test_recorded_sessions_are_tenant_scoped_and_never_select_recovery_copies(
    db: AsyncSession,
) -> None:
    from app.db.models.agent_workspace import AgentWorkspace
    from app.repositories import agent_workspace as workspace_repo

    owner = await _person(db)
    first, other = await _organization(db, owner), await _organization(db, owner)
    change = await _recorded(db, first, owner)
    source = AgentWorkspace(
        organization_id=first.id,
        conversation_id=change.conversation_id,
        scope="conversation",
        scope_key="source",
        backend="service",
        session_id="same",
    )
    db.add(source)
    await db.flush()
    recovery = AgentWorkspace(
        organization_id=first.id,
        conversation_id=change.conversation_id,
        scope="conversation",
        scope_key="recovery",
        backend="service",
        session_id="same",
        recovery_of_id=source.id,
    )
    stranger = AgentWorkspace(
        organization_id=other.id,
        scope="conversation",
        scope_key="stranger",
        backend="service",
        session_id="same",
    )
    db.add_all([recovery, stranger])
    await db.flush()
    assert await workspace_repo.for_session(db, organization_id=first.id, session_id="same") == [
        source
    ]
    from app.repositories import coding_task_change as change_repo

    change.revert_job_id = uuid.uuid4()
    await db.flush()
    assert not await change_repo.has_pending_revert(
        db, organization_id=other.id, conversation_id=change.conversation_id
    )


async def test_a_duplicate_admission_is_refused_without_waiting_on_its_transaction(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    import anyio

    from app.core.exceptions import AlreadyExistsError
    from app.services.workspace_turn_guard import admit

    owner = await _person(db)
    organization = await _organization(db, owner)
    change = await _recorded(db, organization, owner)
    await db.commit()
    await admit(db, organization_id=organization.id, conversation_id=change.conversation_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as second:
        with anyio.fail_after(1), pytest.raises(AlreadyExistsError):
            await CodingTaskChangeService(second).revert(_as(owner, organization), change.id)


async def test_an_inflight_undo_is_refused_without_waiting_on_the_worker_row_lock(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    import anyio

    from app.core.exceptions import AlreadyExistsError
    from app.repositories import coding_task_change as change_repo
    from app.services.background_jobs import enqueue
    from app.worker.jobs import REVERT_CODING_TASK, RevertCodingTask

    owner = await _person(db)
    organization = await _organization(db, owner)
    change = await _recorded(db, organization, owner)
    change.revert_job_id = await enqueue(
        db,
        REVERT_CODING_TASK,
        RevertCodingTask(
            organization_id=organization.id,
            change_id=change.id,
            user_id=owner.id,
            claim_id=uuid.uuid4(),
        ),
        organization_id=organization.id,
    )
    await db.commit()
    await change_repo.get_in_organization(
        db, change.id, organization_id=organization.id, for_update=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as second:
        with anyio.fail_after(1), pytest.raises(AlreadyExistsError):
            await CodingTaskChangeService(second).revert(_as(owner, organization), change.id)


async def test_a_failed_final_transaction_is_reconciled_without_repeating_the_file_effect(
    engine: AsyncEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace, WorkspaceRef

    from app.agents.deps import AgentDeps
    from app.core.exceptions import AlreadyExistsError
    from app.db.models.audit_log import AppAdminAuditLog
    from app.db.models.background_job import BackgroundJob
    from app.repositories import coding_task_change as change_repo
    from app.services.workspace_turn_guard import admit
    from app.worker.attempt import Attempt, running
    from app.worker.jobs import RevertCodingTask
    from app.worker.tasks import coding_tasks

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("before\n")
    monkeypatch.setattr(_changes, "CHANGES_ROOT", str(tmp_path / "snapshots"))
    workspace = Workspace(LocalWorkspaceBackend(root))
    context = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), workspace=workspace)
    baseline = await _changes.begin(context)
    assert baseline is not None
    (root / "app.py").write_text("after\n")
    changes = await _changes.finish(context, baseline)
    assert changes is not None
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = await _person(db)
        organization = await _organization(db, owner)
        conversation = Conversation(
            organization_id=organization.id, user_id=owner.id, title="Recover undo"
        )
        db.add(conversation)
        await db.flush()
        change = await CodingTaskChangeService(db).record(
            changes,
            organization_id=organization.id,
            conversation_id=conversation.id,
            tool_call_id="task",
            harness="codex",
            snapshot_isolated=True,
            workspace_ref=WorkspaceRef(provider="test", id="original"),
        )
        ctx, change_id, conversation_id = _as(owner, organization), change.id, conversation.id
        monkeypatch.setattr(
            SandboxWorkspaceService, "recorded_for_task", AsyncMock(return_value=[])
        )
        queued = await CodingTaskChangeService(db).revert(ctx, change_id)
        assert queued.revert_status == "pending"
        assert change.revert_job_id is not None
        job_id = change.revert_job_id
        job = await db.get(BackgroundJob, job_id)
        assert job is not None
        payload = RevertCodingTask.model_validate(job.payload)
        job.status, job.attempts = "running", 1
        await db.commit()

    sessions: list[AsyncSession] = []

    @asynccontextmanager
    async def transaction() -> AsyncGenerator[AsyncSession]:
        async with factory() as db:
            sessions.append(db)
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    @asynccontextmanager
    async def opened(*args: object, **kwargs: object) -> AsyncGenerator[Workspace]:
        yield workspace

    monkeypatch.setattr(coding_tasks, "get_worker_db_context", transaction)
    monkeypatch.setattr(SandboxWorkspaceService, "open_recorded", opened)
    original_restore = coding_tasks._coding_task_revert.revert

    async def restore(*args: object, **kwargs: object) -> None:
        assert not sessions[-1].in_transaction()
        async with factory() as observer:
            current = await change_repo.get_in_organization(
                observer, change_id, organization_id=ctx.organization_id
            )
            assert current is not None and current.revert_started_at is not None
            assert current.revert_job_id == job_id
            with pytest.raises(AlreadyExistsError):
                await admit(
                    observer, organization_id=ctx.organization_id, conversation_id=conversation_id
                )
        await original_restore(*args, **kwargs)

    monkeypatch.setattr(coding_tasks._coding_task_revert, "revert", restore)
    original_audit = coding_tasks.record_audit

    async def fail_final_commit(*args: object, **kwargs: object) -> None:
        await original_audit(*args, **kwargs)
        raise RuntimeError("simulated persistence failure after the file effect")

    monkeypatch.setattr(coding_tasks, "record_audit", fail_final_commit)
    with running(Attempt(1, 3)), pytest.raises(RuntimeError):
        await coding_tasks.revert_coding_task(payload)
    assert (root / "app.py").read_text() == "before\n"
    async with factory() as db:
        current = await change_repo.get_in_organization(
            db, change_id, organization_id=ctx.organization_id
        )
        assert (
            current is not None and current.reverted_at is None and current.revert_job_id == job_id
        )
        job = await db.get(BackgroundJob, job_id)
        assert job is not None
        assert await coding_tasks.job_repo.get_for_attempt(db, job_id, fence=2) is None
        job.attempts = 2
        await db.commit()
    monkeypatch.setattr(coding_tasks, "record_audit", original_audit)
    with running(Attempt(2, 3)):
        await coding_tasks.revert_coding_task(payload)
        await coding_tasks.revert_coding_task(payload)
    assert (root / "app.py").read_text() == "before\n"
    async with factory() as db:
        current = await change_repo.get_in_organization(
            db, change_id, organization_id=ctx.organization_id
        )
        assert (
            current is not None
            and current.reverted_at is not None
            and current.revert_job_id is None
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AppAdminAuditLog)
                .where(AppAdminAuditLog.target_id == str(change_id))
            )
            == 1
        )
        await admit(db, organization_id=ctx.organization_id, conversation_id=conversation_id)


async def test_run_admission_and_unknown_undo_reservations_share_the_same_barrier(
    db: AsyncSession,
) -> None:
    from datetime import UTC, datetime

    from app.core.exceptions import AlreadyExistsError
    from app.db.models.agent import Agent
    from app.repositories import agent_run as run_repo
    from app.repositories import coding_task_change as change_repo
    from app.services.workspace_turn_guard import admit

    owner = await _person(db)
    organization = await _organization(db, owner)
    change = await _recorded(db, organization, owner)
    agent = Agent(
        organization_id=organization.id, name="Writer", slug="writer", created_by_user_id=owner.id
    )
    db.add(agent)
    await db.flush()
    run = await run_repo.create_run(
        db,
        organization_id=organization.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=owner.id,
        conversation_id=change.conversation_id,
        surface="web",
        model_label=None,
        started_at=datetime.now(UTC),
    )
    assert await run_repo.has_running_in_conversation(
        db, organization_id=organization.id, conversation_id=change.conversation_id
    )
    with pytest.raises(AlreadyExistsError):
        await admit(db, organization_id=organization.id, conversation_id=change.conversation_id)
    await admit(
        db, organization_id=organization.id, conversation_id=change.conversation_id, run_id=run.id
    )
    run.status = "completed"
    change.revert_job_id = uuid.uuid4()
    await db.flush()
    assert await change_repo.has_pending_revert(
        db, organization_id=organization.id, conversation_id=change.conversation_id
    )
    assert not await change_repo.has_pending_revert(
        db,
        organization_id=organization.id,
        conversation_id=change.conversation_id,
        excluding=change.id,
    )
    with pytest.raises(AlreadyExistsError):
        await admit(db, organization_id=organization.id, conversation_id=change.conversation_id)
