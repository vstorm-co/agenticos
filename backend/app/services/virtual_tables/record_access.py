"""Compose row data access without granting table administration."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import GrantLevel
from app.db.models.virtual_table import VirtualTable
from app.repositories import resource_grant_repo, virtual_table_repo
from app.repositories import task as task_repo
from app.schemas.virtual_table import ColumnDef, RecordRead
from app.services.access import TABLE, resolve_access
from app.services.virtual_tables.row_policy import (
    may_edit_row,
    parse_policy,
    policy_columns_valid,
    row_matches,
)


async def can_write_record(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    record_id: UUID,
    columns: list[ColumnDef],
    values: Mapping[str, object],
    *,
    allow_archived: bool = False,
) -> bool:
    """Write may come from a row grant without promoting the member to table editor.

    A receipt replay may omit the archive lifecycle check; all authority checks
    still apply, and a fresh write always requires a live table.
    """
    policy = parse_policy(table.row_policy)
    if not policy_columns_valid(policy, columns):
        return False
    if (
        ctx.user_id is None
        or table.organization_id != ctx.organization_id
        or (table.archived_at is not None and not allow_archived)
        or not ctx.key_allows(Perm.TABLES_EDIT)
    ):
        return False
    if await resolve_access(
        db, ctx, table, Perm.TABLES_EDIT, resource_type=TABLE
    ) and await may_edit_row(db, ctx, table, columns, values):
        return True
    if not await resolve_access(db, ctx, table, Perm.TABLES_VIEW, resource_type=TABLE):
        return False
    if policy is not None and row_matches(values, policy, columns, ctx.user_id, kind="edit"):
        return True
    levels = await resource_grant_repo.record_levels(
        db,
        organization_id=ctx.organization_id,
        subject_user_id=ctx.user_id,
        record_ids=[record_id],
    )
    return levels.get(record_id) is GrantLevel.EDIT


async def protected_columns(
    db: AsyncSession, table: VirtualTable, columns: list[ColumnDef]
) -> list[UUID]:
    """Fields that govern this table or membership inherited by another table."""
    policy = parse_policy(table.row_policy)
    named: set[str] = set()
    if policy is not None and policy.rule == "assignee":
        named.update(
            str(column_id)
            for column_id in (
                policy.view_column_id,
                policy.edit_column_id,
                policy.view_project_link_column_id,
            )
            if column_id is not None
        )
    named.update(
        await virtual_table_repo.referenced_access_columns(
            db, organization_id=table.organization_id, table_id=table.id
        )
    )
    return [column.id for column in columns if str(column.id) in named and not column.archived]


async def require_access_fields(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> None:
    """Data writers cannot change the audience, including through membership links."""
    if await resolve_access(db, ctx, table, Perm.TABLES_EDIT, resource_type=TABLE):
        return
    protected = await protected_columns(db, table, columns)
    if any(before.get(str(column_id)) != after.get(str(column_id)) for column_id in protected):
        raise AuthorizationError(
            message="Changing record access requires table administration",
            details={"table_id": table.id},
        )


async def with_record_access(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    records: list[RecordRead],
) -> list[RecordRead]:
    """Project current authority in one grant query for the page, never into receipts."""
    policy = parse_policy(table.row_policy)
    administrative = (
        table.archived_at is None
        and table.organization_id == ctx.organization_id
        and await resolve_access(db, ctx, table, Perm.TABLES_EDIT, resource_type=TABLE)
    )
    can_manage = (
        administrative and await task_repo.for_table(db, table.id, ctx.organization_id) is None
    )
    levels = (
        await resource_grant_repo.record_levels(
            db,
            organization_id=ctx.organization_id,
            subject_user_id=ctx.user_id,
            record_ids=[record.id for record in records],
        )
        if ctx.user_id is not None and records
        else {}
    )
    protected = [] if administrative else await protected_columns(db, table, columns)
    result: list[RecordRead] = []
    for record in records:
        existing_write = administrative and await may_edit_row(
            db, ctx, table, columns, record.values
        )
        granted_write = (
            (
                levels.get(record.id) is GrantLevel.EDIT
                or (
                    policy is not None
                    and row_matches(record.values, policy, columns, ctx.user_id, kind="edit")
                )
            )
            and ctx.key_allows(Perm.TABLES_EDIT)
            and table.archived_at is None
        )
        result.append(
            record.model_copy(
                update={
                    "access": "write" if existing_write or granted_write else "read",
                    "can_delete": existing_write,
                    "can_manage_access": can_manage,
                    "read_only_column_ids": protected,
                }
            )
        )
    return result
