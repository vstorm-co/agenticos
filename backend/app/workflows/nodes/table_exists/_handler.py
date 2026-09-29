"""`table.exists`: whether a table of this name exists, among those the principal sees.

The name is matched whole and without regard to case, and the step leaves by
`yes` - carrying the table's id - or by `no`, so a workflow can create a table
the first time it runs and reuse it after.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.permissions import AuthContext
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import not_configured, with_service

# The most same-named candidates read to find the exact one: a search is by part
# of a name, and "Leads" also finds "Leads archive".
_CANDIDATES = 100


class TableExistsInput(BaseModel):
    """The table's name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class TableExistsOutput(BaseModel):
    """Whether it exists, and its id when it does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exists: bool
    table_id: UUID | None = None


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`yes` or `no`."""
    if output is None:
        return frozenset()
    return frozenset({"yes" if output.get("exists") else "no"})


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Look the table up by its name."""
    if not isinstance(node_input, TableExistsInput):
        return not_configured("This step needs a table name")
    wanted = node_input.name.strip().casefold()

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        page = await service.list_tables(auth, search=node_input.name.strip(), limit=_CANDIDATES)
        found = next((table for table in page.items if table.name.casefold() == wanted), None)
        return Completed[TableExistsOutput](
            output=TableExistsOutput(
                exists=found is not None, table_id=found.id if found is not None else None
            )
        )

    return await with_service(work)
