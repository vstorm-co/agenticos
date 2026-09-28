"""The public face of Virtual Tables: one class, whatever surface calls it."""

from app.services.virtual_tables.records import RecordOperations
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
