"""Managed tasks keep API scopes, live audience and record state as independent gates."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext, Perm
from app.db.models.task_board import TaskBoard, TaskLink
from app.repositories import virtual_table_repo
from app.services import task_access as access

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_machine_publishers_and_read_scoped_keys_cannot_edit_managed_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    owner = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    assert not await access.scope_allows(
        db, replace(owner, user_id=None), "organization", owner.organization_id, edit=True
    )
    key = replace(owner, key_scopes=frozenset({Perm.TABLES_VIEW}))
    assert not await access.scope_allows(db, key, "private", owner.user_id, edit=True)
    assert await access.scope_allows(db, key, "private", owner.user_id, edit=False)
    assert not await access.scope_allows(
        db, owner, "unsupported", owner.organization_id, edit=False
    )


async def test_grant_only_editors_still_need_a_live_board_and_edit_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    db = MagicMock()
    boards = AsyncMock(return_value=None)
    grants = AsyncMock(return_value=None)
    monkeypatch.setattr(access.task_repo, "for_scope", boards)
    monkeypatch.setattr(access.resource_grant_repo, "get_level", grants)
    assert not await access._may_edit_table(db, ctx, "project", uuid4())
    boards.return_value = TaskBoard(table_id=uuid4())
    assert not await access._may_edit_table(db, ctx, "project", uuid4())
    grants.return_value = "read"
    assert not await access._may_edit_table(db, ctx, "project", uuid4())
    grants.return_value = "edit"
    assert await access._may_edit_table(db, ctx, "project", uuid4())


async def test_orphaned_or_deleted_task_cannot_be_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    link = AsyncMock(return_value=None)
    record = AsyncMock(return_value=None)
    monkeypatch.setattr(access.task_repo, "for_trigger", link)
    monkeypatch.setattr(access.task_repo, "record", record)
    assert not await access.execution_allows(MagicMock(), ctx, uuid4())
    link.return_value = TaskLink(record_id=uuid4())
    assert not await access.execution_allows(MagicMock(), ctx, uuid4())


async def test_table_audience_partitions_allowed_and_denied_managed_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    mine = TaskBoard(table_id=uuid4(), scope_kind="private", scope_id=ctx.user_id)
    other = TaskBoard(table_id=uuid4(), scope_kind="private", scope_id=uuid4())
    monkeypatch.setattr(access.task_repo, "boards", AsyncMock(return_value=[mine, other]))
    assert await access.table_audience(MagicMock(), ctx) == ([mine.table_id], [other.table_id])


@pytest.mark.parametrize("missing", ["authority", "link", "record", "board"])
async def test_start_refuses_work_that_disappears_after_dispatch(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from app.db.models.agent_trigger import AgentTrigger
    from app.db.models.virtual_table import VirtualTableRecord
    from app.services.task_execution import TaskExecution

    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    monkeypatch.setattr(access, "execution_allows", AsyncMock(return_value=missing != "authority"))
    monkeypatch.setattr(
        access.task_repo,
        "for_trigger",
        AsyncMock(return_value=None if missing == "link" else TaskLink(record_id=uuid4())),
    )
    monkeypatch.setattr(
        access.task_repo,
        "record",
        AsyncMock(
            return_value=None if missing == "record" else VirtualTableRecord(table_id=uuid4())
        ),
    )
    monkeypatch.setattr(access.task_repo, "for_table", AsyncMock(return_value=None))
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=None))
    db = MagicMock()
    assert not await TaskExecution(db).started(ctx, AgentTrigger(id=uuid4()))
    db.flush.assert_not_called()


@pytest.mark.parametrize("missing", ["link", "record", "board"])
async def test_unavailable_task_does_not_recreate_deleted_records(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from app.db.models.agent_trigger import AgentTrigger
    from app.db.models.virtual_table import VirtualTableRecord
    from app.services.task_execution import TaskExecution

    monkeypatch.setattr(
        access.task_repo,
        "for_trigger",
        AsyncMock(return_value=None if missing == "link" else TaskLink(record_id=uuid4())),
    )
    monkeypatch.setattr(
        access.task_repo,
        "record",
        AsyncMock(
            return_value=None if missing == "record" else VirtualTableRecord(table_id=uuid4())
        ),
    )
    monkeypatch.setattr(access.task_repo, "for_table", AsyncMock(return_value=None))
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=None))
    db = MagicMock()
    await TaskExecution(db).unavailable(AgentTrigger(id=uuid4(), organization_id=uuid4()))
    db.flush.assert_not_called()


def _board(kind: str, scope_id: object) -> TaskBoard:
    return TaskBoard(scope_kind=kind, scope_id=scope_id, table_id=uuid4())


@pytest.mark.parametrize(
    ("role", "manages"),
    [("owner", True), ("admin", True), ("builder", False), ("member", False)],
)
async def test_only_an_all_scope_editor_changes_the_organizations_board(
    role: str, manages: bool
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=role)
    board = _board("organization", ctx.organization_id)

    assert await access.board_allows(MagicMock(), ctx, board, Perm.TABLES_EDIT)
    assert await access.board_manages(MagicMock(), ctx, board) is manages


async def test_a_board_its_caller_cannot_edit_or_a_keyless_subject_is_never_theirs_to_change() -> (
    None
):
    owner = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    board = _board("organization", owner.organization_id)

    assert not await access.board_manages(MagicMock(), replace(owner, user_id=None), board)
    assert not await access.board_manages(
        MagicMock(), replace(owner, key_scopes=frozenset({Perm.TABLES_VIEW})), board
    )
    assert not await access.board_manages(MagicMock(), owner, _board("unsupported", uuid4()))


async def test_a_private_board_is_its_persons_to_change() -> None:
    member = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")

    assert await access.board_manages(MagicMock(), member, _board("private", member.user_id))
    assert not await access.board_manages(MagicMock(), member, _board("private", uuid4()))


async def test_a_group_board_is_its_leads_to_change(monkeypatch: pytest.MonkeyPatch) -> None:
    member = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    board = _board("group", uuid4())
    membership = MagicMock(is_lead=False)
    monkeypatch.setattr(access.group_repo, "get", AsyncMock(return_value=MagicMock()))
    monkeypatch.setattr(access.group_repo, "get_member", AsyncMock(return_value=membership))

    assert await access.board_allows(MagicMock(), member, board, Perm.TABLES_EDIT)
    assert not await access.board_manages(MagicMock(), member, board)
    membership.is_lead = True
    assert await access.board_manages(MagicMock(), member, board)


async def test_a_project_board_is_its_owners_to_change(monkeypatch: pytest.MonkeyPatch) -> None:
    member = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    board = _board("project", uuid4())
    project = MagicMock(owner_user_id=uuid4())
    monkeypatch.setattr(access.project_repo, "get", AsyncMock(return_value=project))
    monkeypatch.setattr(
        "app.services.access.resolve_access", AsyncMock(return_value=True), raising=True
    )

    assert not await access.board_manages(MagicMock(), member, board)
    project.owner_user_id = member.user_id
    assert await access.board_manages(MagicMock(), member, board)


async def test_only_a_task_board_answers_whether_it_may_be_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(access.task_repo, "for_table", lookup)

    assert await access.manages_table(MagicMock(), owner, uuid4()) is None
    lookup.return_value = _board("organization", owner.organization_id)
    assert await access.manages_table(MagicMock(), owner, uuid4()) is True
