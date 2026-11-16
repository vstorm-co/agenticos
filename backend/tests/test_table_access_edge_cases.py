"""Grant precedence and private linked evidence stay safe at their edge cases."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.repositories import resource_grant_repo, virtual_table_repo
from app.schemas.table_record_access import RecordGrantUpdate
from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables import computed, record_grants, triggers
from app.services.virtual_tables.record_grants import RecordAccessOperations

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ORG = UUID("00000000-0000-4000-8000-000000004001")
USER = UUID("00000000-0000-4000-8000-000000004002")
OWNER = UUID("00000000-0000-4000-8000-000000004003")
TABLE = UUID("00000000-0000-4000-8000-000000004004")
ROW = UUID("00000000-0000-4000-8000-000000004005")
GROUP = UUID("00000000-0000-4000-8000-000000004006")
HIDDEN = UUID("00000000-0000-4000-8000-000000004007")
LINK = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000004008"),
    label="Related",
    type="link",
    link_table_id=TABLE,
)
PRINCIPAL = UUID("00000000-0000-4000-8000-000000004009")


def context() -> AuthContext:
    return AuthContext(user_id=USER, organization_id=ORG, role="member")


def table() -> VirtualTable:
    return VirtualTable(
        id=TABLE,
        organization_id=ORG,
        owner_user_id=OWNER,
        name="Records",
        visibility="org",
        schema_version=1,
        row_policy=None,
        archived_at=None,
    )


async def test_empty_grant_lookup_does_not_query_the_database():
    db = AsyncMock(spec=AsyncSession)
    assert (
        await resource_grant_repo.record_levels(
            db, organization_id=ORG, subject_user_id=USER, record_ids=[]
        )
        == {}
    )
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "levels",
    [
        (GrantLevel.READ, GrantLevel.EDIT),
        (GrantLevel.EDIT, GrantLevel.READ),
    ],
    ids=["read-then-write", "write-then-read"],
)
async def test_write_wins_over_read_regardless_of_grant_query_order(levels):
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = [(ROW, level.value) for level in levels]
    assert await resource_grant_repo.record_levels(
        db, organization_id=ORG, subject_user_id=USER, record_ids=[ROW]
    ) == {ROW: GrantLevel.EDIT}


async def test_broken_destination_policy_columns_hide_links_even_with_a_write_grant(monkeypatch):
    target = table()
    target.row_policy = {
        "rule": "assignee",
        "view_column_id": str(PRINCIPAL),
        "edit_column_id": str(PRINCIPAL),
    }
    grants = AsyncMock(return_value={ROW: GrantLevel.EDIT})
    cells = AsyncMock()
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=target))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(return_value=SimpleNamespace(columns=[])),
    )
    monkeypatch.setattr(virtual_table_repo, "get_record_cells_by_ids", cells)
    monkeypatch.setattr(resource_grant_repo, "record_levels", grants)
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=True))

    assert (
        await computed.visible_link_ids(AsyncMock(spec=AsyncSession), context(), TABLE, {str(ROW)})
        == set()
    )
    grants.assert_not_awaited()
    cells.assert_not_awaited()


@pytest.fixture
def grant_access(monkeypatch):
    db = AsyncMock(spec=AsyncSession)
    service = RecordAccessOperations(db)
    target = table()
    record = VirtualTableRecord(
        id=ROW, organization_id=ORG, table_id=TABLE, schema_version=1, values={}
    )
    load = AsyncMock(return_value=target)
    get_record = AsyncMock(return_value=record)
    monkeypatch.setattr(service, "_load_table", load)
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[]))
    monkeypatch.setattr(record_grants.task_repo, "for_table", AsyncMock(return_value=None))
    monkeypatch.setattr(virtual_table_repo, "get_record", get_record)
    monkeypatch.setattr(resource_grant_repo, "record_levels", AsyncMock(return_value={}))
    return service, target, get_record


async def test_managed_boards_reject_separate_record_grant_management(grant_access, monkeypatch):
    service, _, get_record = grant_access
    monkeypatch.setattr(
        record_grants.task_repo, "for_table", AsyncMock(return_value=SimpleNamespace(id=TABLE))
    )
    with pytest.raises(BadRequestError, match="Managed task boards"):
        await service.get_record_access(context(), TABLE, ROW)
    get_record.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False], ids=["missing-row", "unreadable-row"])
async def test_missing_and_unreadable_rows_share_the_same_grant_management_refusal(
    grant_access, missing
):
    service, target, get_record = grant_access
    if missing:
        get_record.return_value = None
    else:
        target.row_policy = {"rule": "grants"}
    with pytest.raises(NotFoundError, match="Record not found") as error:
        await service.get_record_access(context(), TABLE, ROW)
    assert error.value.details == {"record_id": ROW}


async def test_grant_listing_exposes_only_read_and_write_with_subject_names(
    grant_access, monkeypatch
):
    service, _, _ = grant_access
    grants = [
        SimpleNamespace(
            id=UUID(int=index),
            subject_user_id=user,
            subject_group_id=group,
            level=level.value,
            expires_at=None,
        )
        for index, user, group, level in (
            (1, USER, None, GrantLevel.EDIT),
            (2, None, GROUP, GrantLevel.READ),
            (3, OWNER, None, GrantLevel.USE),
        )
    ]
    monkeypatch.setattr(resource_grant_repo, "list_for_resource", AsyncMock(return_value=grants))
    monkeypatch.setattr(
        record_grants.member_repo,
        "get_emails_for_users",
        AsyncMock(return_value={USER: "reader@example.test"}),
    )
    monkeypatch.setattr(
        record_grants.group_repo, "get_names", AsyncMock(return_value={GROUP: "Reviewers"})
    )

    result = await service.get_record_access(context(), TABLE, ROW)
    assert (result.table_id, result.record_id) == (TABLE, ROW)
    assert [grant.level for grant in result.grants] == ["write", "read"]
    assert result.grants[0].subject_email == "reader@example.test"
    assert result.grants[1].subject_group_name == "Reviewers"


async def test_expired_grant_request_is_rejected_before_membership_or_write(
    grant_access, monkeypatch
):
    service, _, _ = grant_access
    membership = AsyncMock()
    upsert = AsyncMock()
    audit = AsyncMock()
    monkeypatch.setattr(record_grants.member_repo, "get", membership)
    monkeypatch.setattr(resource_grant_repo, "upsert", upsert)
    monkeypatch.setattr(record_grants, "record_audit", audit)

    with pytest.raises(BadRequestError, match="expiry in the future"):
        await service.set_record_grant(
            context(),
            TABLE,
            ROW,
            RecordGrantUpdate(
                subject_user_id=USER,
                level="write",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            ),
        )
    membership.assert_not_awaited()
    upsert.assert_not_awaited()
    audit.assert_not_awaited()


async def test_trigger_projection_skips_invalid_ids_and_keeps_absent_links_absent(monkeypatch):
    db = AsyncMock(spec=AsyncSession)
    readable = AsyncMock(return_value={str(ROW)})
    monkeypatch.setattr(triggers, "visible_link_ids", readable)
    snapshot = triggers._Happened(
        event="updated",
        values={str(LINK.id): [123, "invalid-uuid", str(ROW), str(HIDDEN)], "title": "After"},
        before={"title": "Before"},
        author_id=USER,
    )
    evidence = deepcopy(snapshot)
    result = await triggers.TableTriggerConsumer(db)._publisher_snapshot(
        context(), [LINK], snapshot
    )

    readable.assert_awaited_once_with(db, context(), TABLE, {str(ROW), str(HIDDEN)})
    assert result.values == {str(LINK.id): [str(ROW)], "title": "After"}
    assert result.before == {"title": "Before"}
    assert snapshot == evidence
