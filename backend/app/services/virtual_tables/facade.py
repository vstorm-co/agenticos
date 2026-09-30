"""The public face of Virtual Tables: one class, whatever surface calls it."""

from app.services.virtual_tables.records import RecordOperations
from app.services.virtual_tables.table_views import TableViewOperations
from app.services.virtual_tables.tables import TableOperations


class VirtualTableService(TableOperations, RecordOperations):
    """Tables, schemas and records for the caller's organization.

    The console, agent tools, workflow nodes and the public API all call this class
    with an `AuthContext`; none of them reaches the repository. The organization is
    always read from the context, never from an argument, so there is nowhere to
    ask for another tenant's table.

    Example:
        ```python
        service = VirtualTableService(db)
        table = await service.create_table(ctx, TableCreate(name="Orders", columns=[...]))
        column_id = str(table.columns[0].id)
        written = await service.upsert_record(
            ctx,
            table.id,
            "ORD-1042",
            RecordUpsert(values={column_id: "Acme"}),
            operation_key="import-2026-09-21-row-17",
        )
        # Send the revision back to change it. A stale one raises RevisionConflictError.
        await service.upsert_record(
            ctx,
            table.id,
            "ORD-1042",
            RecordUpsert(values={column_id: "Acme Ltd"}, expected_revision=written.record.revision),
        )
        ```
    """


class TableViewService(TableViewOperations):
    """Saved table/kanban/list views over one table's records.

    A sibling of `VirtualTableService` rather than a mixin folded into it: a view is
    not a table operation, it is a console-only convenience layered over the record
    query the table service already exposes, and keeping it a separate class is what
    lets `app/services/virtual_tables/table_views.py` register its own
    `DependencyChecker` at import time without the table service needing to know
    views exist.
    """
