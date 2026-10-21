"""Naming a parked table call for the person who decides it.

A table write and `share_view` take ids, so an approval card for one used to say
`view_id: 6f1c…` and nothing a person could judge. These describers answer the
ids as the names the card puts into a sentence - the view and its table, or the
table written to - and the gate stores them beside the arguments.

Resolved as `run_person` through the same service reads the console takes, so a
name comes back only if that person may see it; one they may not see, or a run
acting for nobody, answers no context rather than a name. Each opens a short
session of its own, as the tools do, so two gated calls in one model step never
share one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities._members import acting_member
from app.agents.capabilities._registry import ApprovalDescriber
from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.services.virtual_tables.facade import TableViewService, VirtualTableService


async def _person(db: AsyncSession, deps: AgentDeps) -> AuthContext | None:
    if deps.run_person is None:
        return None
    return await acting_member(db, deps.organization_id, str(deps.run_person))


def _id(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


async def describe_share_view(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
    """`{view, table}` for a `share_view` call, or `None` where the person sees neither."""
    async with get_db_context() as db:
        person = await _person(db, deps)
        if person is None:
            return None
        try:
            bound = await TableViewService(db).find_view(person, _id(args["view_id"]))
            table = await VirtualTableService(db).describe_table(person, bound.table_id)
        except AppException:
            return None
        return {"view": bound.view.name, "table": table.name}


async def describe_record_write(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
    """`{table}` for a table write, or `None` where the person cannot see the table.

    The record itself is not named. A record's label is a cell's text - often a
    person's name - and the context is stored on the approval row, read by every
    approver whatever their own access to the table, and kept after the record is
    gone. The arguments already carry what the call writes; the context adds only
    what the ids in them stand for.
    """
    async with get_db_context() as db:
        person = await _person(db, deps)
        if person is None:
            return None
        try:
            table = await VirtualTableService(db).describe_table(person, _id(args["table_id"]))
        except AppException:
            return None
        return {"table": table.name}


APPROVAL_DESCRIBERS: dict[str, ApprovalDescriber] = {
    "share_view": describe_share_view,
    "create_record": describe_record_write,
    "upsert_record": describe_record_write,
    "update_record": describe_record_write,
    "delete_record": describe_record_write,
}
