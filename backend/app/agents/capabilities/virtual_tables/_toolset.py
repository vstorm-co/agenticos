"""The table tools: read and write the Virtual Tables this agent was granted.

Every tool is a thin call into `VirtualTableService` - the same class the
console, the API and workflow nodes call - so conflicts, validation, quotas,
history, receipts and audit are the service's, identical on every surface. What
lives here is only what an agent needs around it: the grant check, a session of
the tool's own, the member rebuilt from current membership (`_access`), and
text the model can read.

Each call opens and commits its own short session rather than sharing the run's:
the run's session is committed before the model is asked anything, so no
connection sits idle through a model call, and a tool call is its own small
transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities._members import acting_member
from app.agents.capabilities.virtual_tables._access import (
    Mistake,
    Refused,
    TableOperation,
    acting_as,
    as_json,
    cell_values,
    is_mistake,
    refusal_text,
    require,
)
from app.agents.deps import AgentDeps
from app.core.exceptions import AppException, NotFoundError
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.schemas.table_view import TableViewConfig, TableViewRead, TableViewUpdate
from app.schemas.virtual_table import (
    ColumnDef,
    ColumnInput,
    RecordCreate,
    RecordFilter,
    RecordQuery,
    RecordSort,
    RecordUpdate,
    RecordUpsert,
    TableCreate,
)
from app.services.virtual_tables.facade import TableViewService, VirtualTableService
from app.services.virtual_tables.presentation import (
    describe_filters,
    filters_by_label,
    labelled,
    schema,
)
from app.services.virtual_tables.receipts import derived_operation_key

logger = logging.getLogger(__name__)

Grants = dict[UUID, frozenset[TableOperation]]


def _operation_key(ctx: RunContext[AgentDeps]) -> str | None:
    """The same key for a retried tool call, a different one for every other call."""
    if ctx.deps.run_id is None or ctx.tool_call_id is None:
        return None
    return derived_operation_key("agent", str(ctx.deps.run_id), ctx.tool_call_id)


async def _call(
    ctx: RunContext[AgentDeps],
    work: Callable[[VirtualTableService, AuthContext], Awaitable[str]],
) -> str:
    """Run `work` as the run's member, in a session of its own, and say how it went."""
    try:
        async with get_db_context() as db:
            auth = await acting_as(db, ctx.deps.organization_id, ctx.deps.user_id)
            return await work(VirtualTableService(db), auth)
    except Refused as refused:
        return str(refused)
    except Mistake as mistake:
        return steer(ctx, str(mistake))
    except AppException as exc:
        if is_mistake(exc):
            return steer(ctx, refusal_text(exc))
        return refusal_text(exc)


async def _call_as_person(
    ctx: RunContext[AgentDeps],
    work: Callable[[TableViewService, VirtualTableService, AuthContext], Awaitable[str]],
) -> str:
    """Run `work` as the member the run answers for, and say how it went.

    Saved views belong to a person: a private one serves data only to its owner. So
    this resolves `run_person`, not the run's `user_id` - which a widget, embed or
    public workflow run sets to its publisher - and refuses a run that has none.
    """
    if ctx.deps.run_person is None:
        return _NO_PERSON
    try:
        async with get_db_context() as db:
            person = await acting_member(db, ctx.deps.organization_id, str(ctx.deps.run_person))
            if person is None:
                return "The member this agent acts for is no longer in the organization."
            return await work(TableViewService(db), VirtualTableService(db), person)
    except Refused as refused:
        return str(refused)
    except Mistake as mistake:
        return steer(ctx, str(mistake))
    except AppException as exc:
        if is_mistake(exc):
            return steer(ctx, refusal_text(exc))
        return refusal_text(exc)


_NO_PERSON = "Only a run acting for a member can use saved views."


def _view_json(
    view: TableViewRead, columns: list[ColumnDef], person: AuthContext
) -> dict[str, Any]:
    config: TableViewConfig = view.config
    return {
        "id": str(view.id),
        "name": view.name,
        "kind": view.kind,
        "visibility": view.visibility,
        "yours": view.owner_user_id == person.subject_id,
        "filters": describe_filters(columns, config.filters),
        "sort": config.sort.model_dump(mode="json"),
        "search": config.search,
    }


def build_tables_toolset(*, grants: Grants, allow_create: bool) -> FunctionToolset[AgentDeps]:
    """The table tools for one binding's grants.

    `grants` is mutated when `create_table` succeeds, so the table it made is
    usable for the rest of this run - under every operation, since its creator
    owns it. The binding's stored config is never changed: the next run starts
    from the grants the spec was published with.
    """
    toolset: FunctionToolset[AgentDeps] = FunctionToolset()

    @toolset.tool
    async def list_tables(ctx: RunContext[AgentDeps]) -> str:
        """List the tables this agent may use, with what it may do in each.

        Use first, to find a table's id. Call describe_table before writing, to
        learn its columns.

        Returns:
            A JSON list of `{id, name, description, operations}`, one per table
            this agent may still reach. A granted table that was archived, deleted
            or is no longer shared with the member the agent acts for is left out.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            found: list[dict[str, Any]] = []
            for table_id, operations in grants.items():
                try:
                    table = await service.describe_table(auth, table_id)
                except AppException:
                    continue
                if table.archived_at is not None:
                    continue
                found.append(
                    {
                        "id": str(table.id),
                        "name": table.name,
                        "description": table.description,
                        "operations": sorted(op.value for op in operations),
                    }
                )
            return as_json(found)

        return await _call(ctx, work)

    @toolset.tool
    async def table_exists(ctx: RunContext[AgentDeps], table_id: UUID) -> str:
        """Check whether a granted table still exists, is live and can be read.

        Args:
            table_id: The table's id, from list_tables.

        Returns:
            `true` or `false` - `false` for an archived table, which takes no writes.
            A table this agent is not granted is refused, not `false`.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.READ)
            try:
                table = await service.describe_table(auth, table_id)
            except NotFoundError:
                return "false"
            return "true" if table.archived_at is None else "false"

        return await _call(ctx, work)

    @toolset.tool
    async def describe_table(ctx: RunContext[AgentDeps], table_id: UUID) -> str:
        """Describe a table's live columns: id, label, type, and options for a select.

        Use before writing: values are keyed by a column's id or its label, and
        must fit its type.

        Args:
            table_id: The table's id, from list_tables.

        Returns:
            A JSON object `{id, name, description, schema_version, columns}`.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.READ)
            return as_json(schema(await service.describe_table(auth, table_id)))

        return await _call(ctx, work)

    @toolset.tool
    async def list_views(ctx: RunContext[AgentDeps], table_id: UUID) -> str:
        """List a table's saved views, to bind a page to one.

        A private view serves data only to you; offer to share it with share_view
        before binding a page others will open to it.

        Args:
            table_id: The table's id, from list_tables.

        Returns:
            A JSON object `{table, views}`: the table as describe_table returns it,
            and each view as `{id, name, kind, visibility, yours, filters, sort,
            search}` - your own views and the shared ones.
        """

        async def work(
            views: TableViewService, service: VirtualTableService, person: AuthContext
        ) -> str:
            require(grants, table_id, TableOperation.READ)
            table = await service.describe_table(person, table_id)
            listed = await views.list_views(person, table_id)
            return as_json(
                {
                    "table": schema(table),
                    "views": [_view_json(view, table.columns, person) for view in listed.items],
                }
            )

        return await _call_as_person(ctx, work)

    @toolset.tool
    async def share_view(ctx: RunContext[AgentDeps], view_id: UUID, reason: str) -> str:
        """Share one of your own private views with the organization.

        Only the view's owner can: sharing lets everyone who may read the table see
        the view's filters and the rows it selects. The person is asked to approve it,
        and `reason` is what tells them why.

        Args:
            view_id: The view's id, from list_views.
            reason: One sentence for the person approving, naming what needs it, e.g.
                "So everyone who opens the page My closed tickets sees its records."

        Returns:
            The view as list_views returns it, now shared.
        """

        async def work(
            views: TableViewService, service: VirtualTableService, person: AuthContext
        ) -> str:
            bound = await views.find_view(person, view_id)
            require(grants, bound.table_id, TableOperation.READ)
            # Before update_view, which also lets a caller with ALL-scope edit manage it.
            if bound.view.owner_user_id != person.subject_id:
                raise Refused("Only the view's owner can share it.")
            shared = await views.update_view(
                person, bound.table_id, view_id, TableViewUpdate(visibility="shared")
            )
            logger.info("View %s shared by its owner: %s", view_id, reason)
            return as_json(_view_json(shared, bound.columns, person))

        return await _call_as_person(ctx, work)

    @toolset.tool
    async def record_exists(ctx: RunContext[AgentDeps], table_id: UUID, external_id: str) -> str:
        """Check whether a record with this external id exists, without reading it.

        Args:
            table_id: The table's id.
            external_id: The record's own key, as it was written.

        Returns:
            `true` or `false`.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.READ)
            return "true" if await service.record_exists(auth, table_id, external_id) else "false"

        return await _call(ctx, work)

    @toolset.tool
    async def list_records(
        ctx: RunContext[AgentDeps],
        table_id: UUID,
        filters: list[RecordFilter] | None = None,
        sort_by: str = "created_at",
        descending: bool = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        skip: Annotated[int, Field(ge=0, le=10_000)] = 0,
    ) -> str:
        """List a table's records, optionally filtered and sorted.

        Args:
            table_id: The table's id.
            filters: Conditions that must all hold: `{column_id, op, value}`, with
                `op` one of eq, neq, gt, gte, lt, lte, contains, in, is_null; a
                select's value is one of its option labels.
            sort_by: `created_at`, `updated_at` or a column id.
            descending: Newest or largest first.
            limit: At most 100.
            skip: How many to skip, for the next page.

        Returns:
            A JSON object `{records, has_more}`. Each record carries `id`,
            `external_id`, `revision` and `values` keyed by column label, a
            select's choice by its label. There
            is no total: `has_more` says whether to ask for the next page.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.READ)
            table = await service.describe_table(auth, table_id)
            page = await service.list_records(
                auth,
                table_id,
                RecordQuery(
                    filters=filters_by_label(table, filters or []),
                    sort=RecordSort(by=sort_by, direction="desc" if descending else "asc"),
                    skip=skip,
                    limit=limit,
                ),
            )
            return as_json(
                {
                    "records": [labelled(table, record) for record in page.items],
                    "has_more": page.has_more,
                }
            )

        return await _call(ctx, work)

    @toolset.tool
    async def get_record(
        ctx: RunContext[AgentDeps],
        table_id: UUID,
        record_id: UUID | None = None,
        external_id: str | None = None,
    ) -> str:
        """Read one record by its id or by its external id.

        Args:
            table_id: The table's id.
            record_id: The record's id. Give this or external_id.
            external_id: The record's own key.

        Returns:
            The record as JSON: `id`, `external_id`, `revision` - send that
            revision back to update or delete it - and `values` by column label.
        """
        if (record_id is None) == (external_id is None):
            return steer(ctx, "Give exactly one of record_id or external_id.")

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.READ)
            table = await service.describe_table(auth, table_id)
            record = (
                await service.get_record(auth, table_id, record_id)
                if record_id is not None
                else await service.get_record_by_external_id(auth, table_id, str(external_id))
            )
            return as_json(labelled(table, record))

        return await _call(ctx, work)

    @toolset.tool
    async def create_record(
        ctx: RunContext[AgentDeps],
        table_id: UUID,
        values: dict[str, Any],
        external_id: str | None = None,
    ) -> str:
        """Add a record to a table.

        To change a record that exists, use update_record; to write one whether or
        not it exists, use upsert_record.

        Args:
            table_id: The table's id.
            values: Cell values keyed by column id or label, each fitting its type;
                a select's value is one of its option labels.
            external_id: Your own key for the record, unique in the table.

        Returns:
            The record as written, with its id and revision 1.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.CREATE)
            table = await service.describe_table(auth, table_id)
            written = await service.create_record(
                auth,
                table_id,
                RecordCreate(external_id=external_id, values=cell_values(table, values)),
                operation_key=_operation_key(ctx),
            )
            return as_json(labelled(table, written.record))

        return await _call(ctx, work)

    @toolset.tool
    async def upsert_record(
        ctx: RunContext[AgentDeps],
        table_id: UUID,
        external_id: str,
        values: dict[str, Any],
        expected_revision: int | None = None,
    ) -> str:
        """Create the record with this external id, or update it if it exists.

        Args:
            table_id: The table's id.
            external_id: The record's own key.
            values: Cell values keyed by column id or label; a select's by option label.
            expected_revision: Required when the record exists: the revision you
                last read. Ignored when it does not.

        Returns:
            The record as written, and whether it was created.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            # Both: an upsert creates the record when nothing holds the key.
            require(grants, table_id, TableOperation.CREATE, TableOperation.UPDATE)
            table = await service.describe_table(auth, table_id)
            written = await service.upsert_record(
                auth,
                table_id,
                external_id,
                RecordUpsert(
                    values=cell_values(table, values), expected_revision=expected_revision
                ),
                operation_key=_operation_key(ctx),
            )
            return as_json({"created": written.created, **labelled(table, written.record)})

        return await _call(ctx, work)

    @toolset.tool
    async def update_record(
        ctx: RunContext[AgentDeps],
        table_id: UUID,
        record_id: UUID,
        expected_revision: int,
        values: dict[str, Any],
    ) -> str:
        """Change some of a record's cells; `null` clears one.

        Args:
            table_id: The table's id.
            record_id: The record's id.
            expected_revision: The revision you last read. If the record changed
                since, nothing is written and you are told its current revision.
            values: Only the cells to change, keyed by column id or label; a
                select's by option label.

        Returns:
            The record as written, with its new revision.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.UPDATE)
            table = await service.describe_table(auth, table_id)
            written = await service.update_record(
                auth,
                table_id,
                record_id,
                RecordUpdate(
                    expected_revision=expected_revision, values=cell_values(table, values)
                ),
                operation_key=_operation_key(ctx),
            )
            return as_json(labelled(table, written.record))

        return await _call(ctx, work)

    @toolset.tool
    async def delete_record(
        ctx: RunContext[AgentDeps], table_id: UUID, record_id: UUID, expected_revision: int
    ) -> str:
        """Delete a record. Its history is kept.

        Args:
            table_id: The table's id.
            record_id: The record's id.
            expected_revision: The revision you last read.

        Returns:
            A confirmation naming the deleted record.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            require(grants, table_id, TableOperation.DELETE)
            await service.delete_record(
                auth,
                table_id,
                record_id,
                expected_revision=expected_revision,
                operation_key=_operation_key(ctx),
            )
            return f"Deleted record {record_id}."

        return await _call(ctx, work)

    async def create_table(
        ctx: RunContext[AgentDeps],
        name: str,
        columns: list[ColumnInput],
        description: str | None = None,
    ) -> str:
        """Create a new table with the given columns.

        Only for making a table that does not exist yet - to add rows, use
        create_record. The table is private to the member this agent acts for.

        Args:
            name: Unique among the organization's live tables, at most 64 characters.
            columns: Each `{label, type}`, with `type` one of text, long_text,
                email, url, phone, number, integer, rating (1 to 5), boolean,
                date, datetime, single_select, multi_select, and
                `options: [{label}]` for a select.
            description: What the table is for.

        Returns:
            The new table as describe_table returns it, with its column ids, for
            the create_record calls that follow.
        """

        async def work(service: VirtualTableService, auth: AuthContext) -> str:
            table = await service.create_table(
                auth,
                TableCreate(name=name, description=description, columns=columns),
                operation_key=_operation_key(ctx),
            )
            grants[table.id] = frozenset(TableOperation)
            return as_json(schema(table))

        return await _call(ctx, work)

    if allow_create:
        # Offered only where the binding enables it, so an agent that may not
        # create tables never sees the tool. The service still requires the
        # member's own `tables:create` when it runs.
        toolset.add_function(create_table)
    return toolset
