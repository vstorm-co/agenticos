"""Schemas for an agent's memory files.

The operator-facing shape of the `memory` capability's file store. `origin` and
`end_user_scope_key` are read-only facts about a row: a person creates trusted
(`operator`) files and never chooses a row's partition key by hand beyond the
optional one on create — the agent's own writes carry `origin="agent"` and a
partition derived server-side from the request.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema

MemoryOriginLiteral = Literal["operator", "agent"]


class AgentMemoryFileRead(BaseSchema):
    id: UUID
    agent_id: UUID
    name: str
    description: str | None = None
    content: str
    format: str
    kind: str
    origin: MemoryOriginLiteral
    # NULL is the shared partition; a `user:<id>`/`chan:<id>` names one end-user's
    # private store. Raw so an operator can see which partition a row is in.
    end_user_scope_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentMemoryFileSummary(BaseSchema):
    """A memory file as the index shows it — without the body.

    The body is the point of the file (the agent reads it, and an operator one
    injects into the prompt), so a listing that carried every body would ship an
    agent's whole memory to draw one table.
    """

    id: UUID
    name: str
    description: str | None = None
    format: str
    kind: str
    origin: MemoryOriginLiteral
    end_user_scope_key: str | None = None
    size_bytes: int = Field(description="The body's size, so the index can hint at its weight")


class AgentMemoryFileList(BaseSchema):
    items: list[AgentMemoryFileSummary]
    total: int


class AgentMemoryFileCreate(BaseSchema):
    agent_id: UUID = Field(description="The agent whose memory this file belongs to")
    name: str = Field(
        min_length=1,
        max_length=64,
        description="How the file is referred to; unique within its partition",
    )
    description: str | None = Field(default=None, max_length=500)
    content: str = Field(default="", description="The file body, as text")
    format: str = Field(
        default="md",
        min_length=1,
        max_length=16,
        description="A hint for fencing and rendering, e.g. `md`, `txt`, `json`",
    )
    kind: str = Field(
        default="note",
        min_length=1,
        max_length=32,
        description="A free-text category shown in the index, e.g. `note`, `profile`",
    )
    end_user_scope_key: str | None = Field(
        default=None,
        max_length=128,
        description="Which end-user partition to write to; omit for the shared store",
    )


class AgentMemoryFileUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None
    format: str | None = Field(default=None, min_length=1, max_length=16)
    kind: str | None = Field(default=None, min_length=1, max_length=32)


class AgentMemoryFactRead(BaseSchema):
    """One remembered fact, as an operator reviews it.

    There is no create or update shape: operators never author facts (a query an
    operator typed would embed off the run's ledger), so the only writes here are
    the agent's own runtime `remember`. Content is included because a fact is
    short by nature - the listing is the content.
    """

    id: UUID
    agent_id: UUID
    content: str
    end_user_scope_key: str | None = None
    created_at: datetime | None = None


class AgentMemoryFactList(BaseSchema):
    items: list[AgentMemoryFactRead]
    total: int
