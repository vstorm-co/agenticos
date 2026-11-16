"""Row-level access: one policy per table, evaluated as a predicate.

A policy says which rows a caller may see and change, by the members a row's
columns name. Enforcement lives in exactly one place per surface:

- listings, counts and exports append the policy as an extra SQL expression to
  the filter clauses (`view_expression`), so paging, sorting and `has_more`
  stay consistent - a post-filter in Python would break pagination;
- single reads and writes evaluate one row's values in Python
  (`may_view_row` / `may_edit_row`), because they fetch by id, not through the
  listing query.

The bypass is narrow on purpose: the deployment superadmin, the table owner
and Owner/Admin roles skip the predicate. Builders and Operators do not - they
hold `tables:view` over all tables today, so applying the rule to them narrows
what they see, and that is deliberate. A context with no subject sees no rows:
there is no person for the predicate to match.

A policy that names a column that is gone, archived or of the wrong type
matches nothing rather than everything: the guards at set time and on schema
change keep that from happening, and this is the backstop.
"""

import logging
from collections.abc import Collection, Mapping
from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import ColumnElement, false
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.virtual_table import VirtualTable
from app.repositories import virtual_table_repo
from app.repositories.virtual_table import FilterClause, SqlKind, policy_expression
from app.schemas.virtual_table import ColumnDef, RowPolicy, RowPolicyUpdate
from app.services.virtual_tables.deadline import ReadDeadline, arm_if_set
from app.services.virtual_tables.exceptions import InvalidRowPolicyError

logger = logging.getLogger(__name__)

_PRINCIPAL_COLUMNS = frozenset({"user", "multi_user"})
"""The column types a row policy may read: one member, or several."""


def parse_policy(raw: dict[str, object] | None) -> RowPolicy | None:
    """The stored policy document, or `None` for no policy.

    A malformed document refuses record access until an authorized table editor
    repairs it. Only an absent document or an explicitly valid `none` policy
    means unrestricted rows; schema drift must never widen the audience.
    """
    if raw is None:
        return None
    try:
        configured = RowPolicyUpdate.model_validate(raw)
        if configured.rule == "none":
            return None
        policy = RowPolicy.model_validate(raw)
    except ValidationError:
        logger.warning("Stored row policy is invalid; refusing record access")
        raise InvalidRowPolicyError() from None
    return policy


def bypasses_policy(ctx: AuthContext, *, owner_user_id: UUID | None) -> bool:
    """Whether `ctx` skips the predicate: superadmin, table owner, Owner/Admin.

    Everyone else - Builder, Operator, Member, Viewer, and any grant holder -
    is filtered by it. A subject-less context never bypasses: there is no
    person to be the owner or the role.
    """
    if ctx.is_app_admin:
        return True
    subject = ctx.user_id
    if subject is None:
        return False
    if owner_user_id is not None and owner_user_id == subject:
        return True
    return ctx.role in {OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value}


def _driving(column_id: UUID, columns: list[ColumnDef]) -> ColumnDef | None:
    """The live column a policy names, or `None` when it is gone or archived."""
    column = next((column for column in columns if column.id == column_id), None)
    return column if column is not None and not column.archived else None


def _assignee_clause(
    policy: RowPolicy, columns: list[ColumnDef], subject: UUID, *, kind: Literal["view", "edit"]
) -> FilterClause | None:
    """The caller's membership in the policy's driving column, as one clause.

    A `user` column holds one member id as text; a `multi_user` column holds
    several as a JSON array. Any other type, or a column that is gone, is not
    a clause the predicate can use - the caller then matches nothing.
    """
    column_id = policy.view_column_id if kind == "view" else policy.edit_column_id
    column = _driving(column_id, columns)
    if column is None or column.type not in _PRINCIPAL_COLUMNS:
        return None
    if column.type == "user":
        return FilterClause(column_id=column.id, kind=SqlKind.TEXT, op="eq", value=str(subject))
    return FilterClause(column_id=column.id, kind=SqlKind.ARRAY, op="contains", value=str(subject))


async def visible_project_ids(
    db: AsyncSession,
    ctx: AuthContext,
    policy: RowPolicy | None,
    *,
    deadline: ReadDeadline | None = None,
) -> list[UUID]:
    """The projects `ctx` belongs to, for the project half of viewing.

    A two-step read, recursion depth one: first the records of the Projects
    table whose members column contains the caller - under that table's own
    row policy, assignee half only, so a project policy cannot smuggle in a
    second project hop - then the caller passes those ids to the link column.
    When the project half cannot be resolved - no policy, no Projects table,
    an archived one, or a missing members column - the answer is empty and
    viewing degrades to assignee-only, never wider.
    """
    if policy is None or (
        policy.view_project_link_column_id is None
        or policy.view_projects_table_id is None
        or policy.view_project_members_column_id is None
    ):
        return []
    await arm_if_set(db, deadline)
    projects = await virtual_table_repo.get_table(
        db, policy.view_projects_table_id, organization_id=ctx.organization_id
    )
    if projects is None or projects.archived_at is not None:
        logger.warning(
            "Row policy on table %s names a projects table that cannot be read; "
            "viewing degrades to assignee-only",
            policy.view_projects_table_id,
        )
        return []
    await arm_if_set(db, deadline)
    version = await virtual_table_repo.get_schema_version(
        db, table_id=projects.id, version=projects.schema_version
    )
    project_columns = [ColumnDef.model_validate(column) for column in version.columns]
    members = _driving(policy.view_project_members_column_id, project_columns)
    if members is None or members.type not in _PRINCIPAL_COLUMNS:
        logger.warning(
            "Row policy on table %s names a members column that cannot be read; "
            "viewing degrades to assignee-only",
            policy.view_projects_table_id,
        )
        return []
    subject = ctx.user_id
    if subject is None:
        return []
    filters = [
        FilterClause(
            column_id=members.id,
            kind=SqlKind.TEXT if members.type == "user" else SqlKind.ARRAY,
            op="eq" if members.type == "user" else "contains",
            value=str(subject),
        )
    ]
    try:
        own = parse_policy(projects.row_policy)
    except InvalidRowPolicyError:
        return []
    if own is not None and not bypasses_policy(ctx, owner_user_id=projects.owner_user_id):
        own_clause = _assignee_clause(own, project_columns, subject, kind="view")
        if own_clause is None:
            return []
        filters.append(own_clause)
    await arm_if_set(db, deadline)
    return await virtual_table_repo.list_record_ids(
        db,
        table_id=projects.id,
        organization_id=ctx.organization_id,
        filters=filters,
    )


def row_matches(
    values: Mapping[str, object],
    policy: RowPolicy,
    columns: list[ColumnDef],
    subject: UUID | None,
    *,
    kind: Literal["view", "edit"],
    project_ids: Collection[UUID] = (),
) -> bool:
    """Whether one row's values pass the policy for `subject`, in Python.

    The view half is the assignee column, or the row's project link naming a
    project in `project_ids`; the edit half is the assignee column alone. A
    row with an empty assignee matches nobody. A missing driving column, or no
    subject at all, matches nobody too.
    """
    if subject is None:
        return False
    column_id = policy.view_column_id if kind == "view" else policy.edit_column_id
    column = _driving(column_id, columns)
    if column is None or column.type not in _PRINCIPAL_COLUMNS:
        return False
    cell = values.get(str(column.id))
    if column.type == "user":
        matched = isinstance(cell, str) and cell == str(subject)
    else:
        matched = isinstance(cell, list) and str(subject) in {str(item) for item in cell}
    if matched or kind == "edit":
        return matched
    link_column_id = policy.view_project_link_column_id
    if link_column_id is None or not project_ids:
        return False
    linked = values.get(str(link_column_id))
    if not isinstance(linked, list):
        return False
    wanted = {str(project_id) for project_id in project_ids}
    return bool(wanted & {str(item) for item in linked})


async def _may(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    values: Mapping[str, object],
    *,
    kind: Literal["view", "edit"],
    project_ids: list[UUID] | None = None,
) -> bool:
    """Whether `ctx` may see (`view`) or change (`edit`) one row's values."""
    policy = parse_policy(table.row_policy)
    if policy is None or bypasses_policy(ctx, owner_user_id=table.owner_user_id):
        return True
    if kind == "view" and project_ids is None:
        project_ids = await visible_project_ids(db, ctx, policy)
    return row_matches(
        values, policy, columns, ctx.user_id, kind=kind, project_ids=project_ids or ()
    )


async def may_view_row(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    values: Mapping[str, object],
    *,
    project_ids: list[UUID] | None = None,
) -> bool:
    """Whether `ctx` may see one row's values: the view predicate, in Python."""
    return await _may(db, ctx, table, columns, values, kind="view", project_ids=project_ids)


async def may_edit_row(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    values: Mapping[str, object],
) -> bool:
    """Whether `ctx` may change one row's values: the edit predicate, in Python."""
    return await _may(db, ctx, table, columns, values, kind="edit")


async def view_expression(
    db: AsyncSession,
    ctx: AuthContext,
    table: VirtualTable,
    columns: list[ColumnDef],
    *,
    deadline: ReadDeadline | None = None,
) -> ColumnElement[bool] | None:
    """The SQL predicate for what `ctx` may see of `table`, or `None` when unfiltered.

    `None` means no policy, or a caller who bypasses it. Anything else is an
    expression the listing query ANDs with the caller's filters - including
    `false()` when the policy names a column it cannot use, or the caller has
    no subject: such a caller sees no rows, rather than every row.
    """
    policy = parse_policy(table.row_policy)
    if policy is None or bypasses_policy(ctx, owner_user_id=table.owner_user_id):
        return None
    subject = ctx.user_id
    if subject is None:
        return false()
    clause = _assignee_clause(policy, columns, subject, kind="view")
    if clause is None:
        return false()
    project_ids = await visible_project_ids(db, ctx, policy, deadline=deadline)
    return policy_expression(
        clause,
        link_column_id=policy.view_project_link_column_id,
        project_ids=project_ids,
    )
