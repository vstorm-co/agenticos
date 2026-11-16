"""Read/Write row grants are data permissions, never administration permissions."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import GrantLevel
from app.schemas.table_record_access import RecordGrantUpdate
from app.schemas.virtual_table import (
    ColumnDef,
    RecordBatchCreate,
    RecordBatchFailure,
    RecordBatchResult,
    RecordCreate,
    RecordRead,
    RowPolicyUpdate,
)
from app.services.virtual_tables import record_access, row_policy
from app.services.virtual_tables.records import RecordOperations

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def access(monkeypatch):
    org, owner, user, row_id = uuid4(), uuid4(), uuid4(), uuid4()
    table = SimpleNamespace(
        id=uuid4(),
        organization_id=org,
        owner_user_id=owner,
        archived_at=None,
        row_policy={"rule": "grants"},
    )
    ctx = AuthContext(user_id=user, organization_id=org, role="viewer")
    db = AsyncMock()
    grants = AsyncMock(return_value={})
    monkeypatch.setattr(record_access.resource_grant_repo, "record_levels", grants)
    monkeypatch.setattr(
        record_access.virtual_table_repo, "referenced_access_columns", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(record_access.task_repo, "for_table", AsyncMock(return_value=None))

    async def table_access(db, ctx, resource, perm, **kwargs):
        return perm == Perm.TABLES_VIEW

    monkeypatch.setattr(record_access, "resolve_access", table_access)
    return db, ctx, table, row_id, grants


@pytest.mark.parametrize("level", [None, GrantLevel.READ, GrantLevel.EDIT, GrantLevel.USE])
async def test_only_a_write_row_grant_allows_cell_writes(access, level):
    db, ctx, table, row_id, grants = access
    grants.return_value = {} if level is None else {row_id: level}
    assert await record_access.can_write_record(db, ctx, table, row_id, [], {}) is (
        level is GrantLevel.EDIT
    )


@pytest.mark.parametrize("level", [GrantLevel.READ, GrantLevel.EDIT])
async def test_read_and_write_row_grants_both_allow_reading(access, level):
    db, ctx, table, row_id, grants = access
    grants.return_value = {row_id: level}
    assert await row_policy.may_view_row(db, ctx, table, [], {}, record_id=row_id)
    # The legacy edit predicate still governs delete; a row Write grant cannot widen it.
    assert not await row_policy.may_edit_row(db, ctx, table, [], {})


async def test_write_grants_do_not_promote_delete_or_manage_access_flags(access):
    db, ctx, table, row_id, grants = access
    grants.return_value = {row_id: GrantLevel.EDIT}
    record = RecordRead(
        id=row_id,
        table_id=table.id,
        external_id=None,
        schema_version=1,
        values={},
        revision=1,
        created_at=datetime.now(UTC),
    )
    result = (await record_access.with_record_access(db, ctx, table, [], [record]))[0]
    assert result.access == "write"
    assert not result.can_delete
    assert not result.can_manage_access
    grants.assert_awaited_once()


async def test_the_write_field_grants_data_write_and_read_without_table_administration(access):
    db, ctx, table, row_id, _ = access
    reader = ColumnDef(id=uuid4(), label="Reader", type="user")
    writer = ColumnDef(id=uuid4(), label="Writer", type="multi_user")
    table.row_policy = {
        "rule": "assignee",
        "view_column_id": str(reader.id),
        "edit_column_id": str(writer.id),
    }
    values = {str(reader.id): str(uuid4()), str(writer.id): [str(ctx.user_id)]}
    columns = [reader, writer]
    assert await record_access.can_write_record(db, ctx, table, row_id, columns, values)
    assert await row_policy.may_view_row(db, ctx, table, columns, values, record_id=row_id)
    record = RecordRead(
        id=row_id,
        table_id=table.id,
        external_id=None,
        schema_version=1,
        values=values,
        revision=1,
        created_at=datetime.now(UTC),
    )
    read = (await record_access.with_record_access(db, ctx, table, columns, [record]))[0]
    assert read.access == "write" and not read.can_delete and not read.can_manage_access


async def test_a_read_only_key_caps_a_members_write_grant(access):
    db, ctx, table, row_id, grants = access
    grants.return_value = {row_id: GrantLevel.EDIT}
    key = AuthContext(
        user_id=ctx.user_id,
        organization_id=ctx.organization_id,
        role=ctx.role,
        api_key_id=uuid4(),
        key_scopes=frozenset({Perm.TABLES_VIEW}),
    )
    assert not await record_access.can_write_record(db, key, table, row_id, [], {})
    grants.assert_not_awaited()


async def test_a_row_grant_never_replaces_access_to_its_table(access, monkeypatch):
    db, ctx, table, row_id, grants = access
    grants.return_value = {row_id: GrantLevel.EDIT}
    monkeypatch.setattr(record_access, "resolve_access", AsyncMock(return_value=False))
    assert not await record_access.can_write_record(db, ctx, table, row_id, [], {})
    grants.assert_not_awaited()


async def test_no_subject_a_foreign_organization_and_an_archive_cannot_use_a_write_grant(access):
    db, ctx, table, row_id, grants = access
    grants.return_value = {row_id: GrantLevel.EDIT}
    for other in (
        AuthContext(user_id=None, organization_id=ctx.organization_id, role="viewer"),
        AuthContext(user_id=ctx.user_id, organization_id=uuid4(), role="owner"),
    ):
        assert not await record_access.can_write_record(db, other, table, row_id, [], {})
    table.archived_at = datetime.now(UTC)
    assert not await record_access.can_write_record(db, ctx, table, row_id, [], {})
    grants.assert_not_awaited()


async def test_broken_policy_columns_cannot_be_bypassed_by_a_write_grant(access):
    db, ctx, table, row_id, grants = access
    table.row_policy = {
        "rule": "assignee",
        "view_column_id": str(uuid4()),
        "edit_column_id": str(uuid4()),
    }
    grants.return_value = {row_id: GrantLevel.EDIT}
    assert not await record_access.can_write_record(db, ctx, table, row_id, [], {})
    assert not await row_policy.may_view_row(db, ctx, table, [], {}, record_id=row_id)
    grants.assert_not_awaited()


async def test_data_writers_cannot_change_audience_fields_or_parent_membership(access, monkeypatch):
    db, ctx, table, _, _ = access
    reader = ColumnDef(id=uuid4(), label="Reader", type="user")
    writer = ColumnDef(id=uuid4(), label="Writer", type="multi_user")
    members = ColumnDef(id=uuid4(), label="Members", type="multi_user")
    title = ColumnDef(id=uuid4(), label="Title", type="text")
    table.row_policy = {
        "rule": "assignee",
        "view_column_id": str(reader.id),
        "edit_column_id": str(writer.id),
    }
    monkeypatch.setattr(
        record_access.virtual_table_repo,
        "referenced_access_columns",
        AsyncMock(return_value={str(members.id)}),
    )
    columns = [reader, writer, members, title]
    before = {str(reader.id): str(ctx.user_id), str(writer.id): [], str(members.id): []}
    await record_access.require_access_fields(
        db, ctx, table, columns, before, {**before, str(title.id): "A new title"}
    )
    for column in (reader, writer, members):
        with pytest.raises(AuthorizationError):
            await record_access.require_access_fields(
                db, ctx, table, columns, before, {**before, str(column.id): [str(uuid4())]}
            )


def test_the_public_contract_accepts_read_or_write_and_exactly_one_subject():
    user, group = uuid4(), uuid4()
    assert RecordGrantUpdate(subject_user_id=user, level="write").level == "write"
    assert RecordGrantUpdate(subject_group_id=group, level="read").level == "read"
    for body in (
        {"subject_user_id": user, "level": "edit"},
        {"subject_user_id": user, "level": "use"},
        {"subject_user_id": user, "subject_group_id": group, "level": "read"},
        {"level": "read"},
        {"subject_user_id": user, "level": "write", "can_delete": True},
    ):
        with pytest.raises(ValidationError):
            RecordGrantUpdate.model_validate(body)
    assert RowPolicyUpdate(rule="grants").view_column_id is None
    with pytest.raises(ValidationError):
        RowPolicyUpdate(rule="grants", view_column_id=user)


@pytest.mark.parametrize("malformed", [False, True])
async def test_a_batch_receipt_refuses_missing_or_malformed_error_record_ids(
    access, monkeypatch, malformed
):
    db, ctx, table, row_id, _ = access
    service = RecordOperations(db)
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        record_access.virtual_table_repo, "get_record", AsyncMock(return_value=None)
    )
    result = RecordBatchResult(
        created=0,
        failed=[
            RecordBatchFailure(
                index=0,
                code="REVISION_CONFLICT",
                message="Changed",
                details={
                    "record_id": "invalid" if malformed else str(row_id),
                    "current_revision": 2,
                },
            )
        ],
        as_of=datetime.now(UTC),
    )
    with pytest.raises(NotFoundError) as refused:
        await service._authorize_batch_replay(
            ctx, table, RecordBatchCreate(records=[RecordCreate(values={})]), result
        )
    assert refused.value.details == {"table_id": table.id}


async def test_a_batch_receipt_reauthorizes_cached_error_ids_without_an_external_id(
    access, monkeypatch
):
    db, ctx, table, row_id, grants = access
    service = RecordOperations(db)
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        record_access.virtual_table_repo,
        "get_record",
        AsyncMock(return_value=SimpleNamespace(id=row_id, values={})),
    )
    result = RecordBatchResult(
        created=0,
        failed=[
            RecordBatchFailure(index=0, code="INVALID_RECORD", message="Invalid", details=None),
            RecordBatchFailure(index=1, code="INVALID_RECORD", message="Invalid", details={}),
            RecordBatchFailure(
                index=2,
                code="REVISION_CONFLICT",
                message="Changed",
                details={"record_id": str(row_id), "current_revision": 2},
            ),
        ],
        as_of=datetime.now(UTC),
    )
    data = RecordBatchCreate(records=[RecordCreate(values={}) for _ in range(3)])
    grants.return_value = {row_id: GrantLevel.EDIT}
    await service._authorize_batch_replay(ctx, table, data, result)
    grants.return_value = {row_id: GrantLevel.READ}
    with pytest.raises(NotFoundError) as refused:
        await service._authorize_batch_replay(ctx, table, data, result)
    assert refused.value.details == {"table_id": table.id}


async def test_a_batch_receipt_keeps_aggregate_counts_when_an_external_id_no_longer_exists(
    access, monkeypatch
):
    db, ctx, table, _, grants = access
    service = RecordOperations(db)
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[]))
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(record_access.virtual_table_repo, "get_record_by_external_id", lookup)
    result = RecordBatchResult(created=1, failed=[], as_of=datetime.now(UTC))
    original = result.model_dump()
    await service._authorize_batch_replay(
        ctx, table, RecordBatchCreate(records=[RecordCreate(external_id="removed")]), result
    )
    assert result.model_dump() == original
    lookup.assert_awaited_once_with(
        db, "removed", table_id=table.id, organization_id=ctx.organization_id
    )
    grants.assert_not_awaited()
