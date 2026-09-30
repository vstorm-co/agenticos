"""The dependency checker for table triggers (#1785), kept apart from the service.

`app.services.virtual_tables` imports this at package import, so the checker is
registered in every process that can archive a column. The trigger service and
consumer import the workflow execution facade, which imports this package back,
so they stay out of the package's own import.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.repositories import virtual_table_trigger as trigger_repo
from app.repositories import workflow as workflow_repo
from app.services.access import WORKFLOW, resolve_access
from app.services.virtual_tables.dependencies import Dependent, register_dependency_checker


async def table_trigger_dependents(
    db: AsyncSession,
    *,
    organization_id: UUID,
    table_id: UUID,
    column_ids: frozenset[UUID] | None,
    caller: AuthContext,
) -> list[Dependent]:
    """Triggers that filter on a column being archived - paused ones too, which
    would otherwise come back on filtering on a column that is gone.

    Archiving the whole table is not refused: its triggers fire on nothing once
    it takes no writes. A trigger is fixed in its workflow - the trigger node's
    filters, then a publish - and is named after that workflow, to a caller
    who may open it, so they know which one to change.
    """
    if column_ids is None:
        return []
    named = {str(column_id) for column_id in column_ids}
    found: list[Dependent] = []
    for trigger in await trigger_repo.list_for_table(
        db, table_id=table_id, organization_id=organization_id
    ):
        filtered = {str(item.get("column_id")) for item in trigger.filters}
        if named & filtered:
            workflow = await workflow_repo.get(
                db, trigger.workflow_id, organization_id=organization_id
            )
            name = None
            if workflow is not None and await resolve_access(
                db, caller, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW
            ):
                name = workflow.name
            found.append(Dependent(kind="table_trigger", id=trigger.id, name=name))
    return found


register_dependency_checker(table_trigger_dependents)
