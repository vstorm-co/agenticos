"""Identity references never confer authority and never cross an organization."""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.repositories import agent_repo, member_repo
from app.schemas.virtual_table import CellValue, ColumnDef
from app.services.access import AGENT, accessible_ids

PRINCIPAL_TYPES = frozenset({"user", "multi_user", "agent", "multi_agent"})


async def principal_problems(
    db: AsyncSession,
    ctx: AuthContext,
    columns: Sequence[ColumnDef],
    values: Mapping[str, CellValue],
) -> list[tuple[str, str]]:
    """Batch membership and visibility checks for normalized reference values."""
    users: set[UUID] = set()
    agents: set[UUID] = set()
    references: list[tuple[ColumnDef, set[UUID]]] = []
    for column in columns:
        if column.archived or column.type not in PRINCIPAL_TYPES:
            continue
        value = values.get(str(column.id))
        ids = (
            {UUID(item) for item in value}
            if isinstance(value, list)
            else {UUID(value)}
            if isinstance(value, str)
            else set()
        )
        if not ids:
            continue
        references.append((column, ids))
        (users if column.type in {"user", "multi_user"} else agents).update(ids)
    valid_users = (
        set(
            await member_repo.get_active_ids(
                db, organization_id=ctx.organization_id, user_ids=list(users)
            )
        )
        if users
        else set()
    )
    rows = (
        await agent_repo.get_many(db, list(agents), organization_id=ctx.organization_id)
        if agents
        else {}
    )
    valid_agents = (
        await accessible_ids(db, ctx, rows.values(), Perm.AGENTS_VIEW, resource_type=AGENT)
        if rows
        else set()
    )
    return [
        (
            str(column.id),
            "Choose active members of this organization"
            if column.type in {"user", "multi_user"}
            else "Choose agents you can access in this organization",
        )
        for column, ids in references
        if not ids.issubset(valid_users if column.type in {"user", "multi_user"} else valid_agents)
    ]
