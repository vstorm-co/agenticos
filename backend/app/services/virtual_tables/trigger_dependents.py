"""The dependency checker for table triggers (#1785), kept apart from the service.

`app.services.virtual_tables` imports this at package import, so the checker is
registered in every process that can archive a column. The trigger service and
consumer import the workflow execution facade, which imports this package back,
so they stay out of the package's own import.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.repositories import virtual_table_trigger as trigger_repo
from app.services.virtual_tables.dependencies import Dependent, register_dependency_checker


async def table_trigger_dependents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    column_ids: frozenset[UUID] | None,
    caller: AuthContext,
) -> list[Dependent]:
    """Triggers that filter or map on a column being archived - switched off ones
    too, which would otherwise come back on filtering on a column that is gone.

    Archiving the whole table is not refused: its triggers fire on nothing once
    it takes no writes, and deleting them is a separate decision. Every trigger
    is the caller's to fix, since `tables:edit` on the table is what changing or
    removing one takes.
    """
    if column_ids is None:
        return []
    named = {str(column_id) for column_id in column_ids}
    found: list[Dependent] = []
    for trigger in await trigger_repo.list_for_table(
        db, table_id=table_id, organization_id=organization_id
    ):
        filtered = {str(item.get("column_id")) for item in trigger.filters}
        mapped = set(trigger.input_mapping.values())
        if named & (filtered | mapped):
            found.append(Dependent(kind="table_trigger", id=trigger.id))
    return found


register_dependency_checker(table_trigger_dependents)
