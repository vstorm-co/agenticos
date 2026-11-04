"""Naming a parked table call for the person who decides it.

A table write takes ids, so an approval card for one used to say `table_id: 6f1c…`
and nothing a person could judge. These describers answer the ids as the names the
card puts into a sentence - the table written to - and the gate stores them beside
the arguments.

Resolved as `run_person` through the same service reads the console takes, so a
name comes back only if that person may see it; one they may not see, or a member
run for nobody, answers no context rather than a name. A run that is its agent is
resolved as the agent, which sees only the tables its spec grants. Either way a
table the run was not granted is never named (`describers_for`). Each opens a short
session of its own, as the tools do, so two gated calls in one model step never
share one.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities._registry import ApprovalDescriber
from app.agents.capabilities.virtual_tables._access import TableOperation
from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel
from app.db.session import get_db_context
from app.services.access import TABLE, acting_member, agent_context
from app.services.virtual_tables.facade import VirtualTableService


async def _person(db: AsyncSession, deps: AgentDeps) -> AuthContext | None:
    if deps.run_person is None:
        return None
    return await acting_member(db, deps.organization_id, str(deps.run_person))


def _id(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


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
    "create_record": describe_record_write,
    "upsert_record": describe_record_write,
    "update_record": describe_record_write,
    "delete_record": describe_record_write,
}


def describers_for(
    grants: Mapping[UUID, frozenset[TableOperation]],
) -> dict[str, ApprovalDescriber]:
    """The table describers of one run, closed over the tables its spec grants.

    A table is named only when it is one of `grants`: a model that puts another id in
    a gated call gets a card with no name for it, however visible that table is to
    the person deciding. A run that is its agent resolves the name as the agent, whose
    only reach is `read` on that one granted table; a member's run resolves it as before.
    """

    async def describe(deps: AgentDeps, args: Mapping[str, Any]) -> dict[str, str] | None:
        table_id = _id(args["table_id"])
        if table_id not in grants:
            return None
        if not deps.acts_as_agent:
            return await describe_record_write(deps, args)
        if deps.organization_id is None or deps.agent_id is None:
            return None
        agent = agent_context(
            organization_id=deps.organization_id,
            agent_id=deps.agent_id,
            grants=[(TABLE, table_id, GrantLevel.READ)],
        )
        async with get_db_context() as db:
            try:
                table = await VirtualTableService(db).describe_table(agent, table_id)
            except AppException:
                return None
            return {"table": table.name}

    return dict.fromkeys(APPROVAL_DESCRIBERS, describe)
