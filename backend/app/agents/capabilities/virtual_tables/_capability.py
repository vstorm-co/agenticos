"""Letting an agent read and write the Virtual Tables its binding grants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.virtual_tables._access import TableOperation
from app.agents.capabilities.virtual_tables._toolset import Grants, build_tables_toolset


class TableGrant(BaseModel):
    """One table this agent may use, and what it may do there."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_id: UUID
    operations: tuple[TableOperation, ...] = Field(
        default=(TableOperation.READ,),
        min_length=1,
        description="read, create, update and delete records. An upsert needs create and update.",
    )


class VirtualTablesConfig(BaseModel):
    """Which tables an agent may use, and whether it may create new ones."""

    model_config = ConfigDict(extra="forbid")

    tables: list[TableGrant] = Field(default_factory=list, max_length=50)
    allow_create: bool = Field(
        default=False,
        description=(
            "Let the agent create new tables. The member it acts for still needs the "
            "tables:create permission."
        ),
    )

    @field_validator("tables")
    @classmethod
    def _one_grant_per_table(cls, tables: list[TableGrant]) -> list[TableGrant]:
        ids = [grant.table_id for grant in tables]
        if len(set(ids)) != len(ids):
            raise ValueError("Grant each table once")
        return tables


@dataclass
class VirtualTables(AbstractCapability[AgentDepsT]):
    """Reads and writes the tables the binding grants, through `VirtualTableService`.

    Which tables, and which operations, are the binding's configuration - part of
    the published spec, which the model cannot rewrite. A tool call naming any
    other table is refused before the service runs, and the service's own access
    check still runs on every call, as the member the run acts for.
    """

    grants: Grants = field(default_factory=dict)
    allow_create: bool = False

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The table tools, built once per capability instance - that is, per run."""
        if self._toolset is None:
            self._toolset = build_tables_toolset(grants=self.grants, allow_create=self.allow_create)
        return self._toolset
