"""Schemas for an agent's memory files.

The operator-facing shape of the `memory` capability's file store. `origin` and
`end_user_scope_key` are read-only facts about a row: a person creates trusted
(`operator`) files and never chooses a row's partition key by hand beyond the
optional one on create — the agent's own writes carry `origin="agent"` and a
partition derived server-side from the request.
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from app.schemas.base import BaseSchema

MemoryOriginLiteral = Literal["operator", "agent"]

# The shapes `derive_end_user_scope_key` produces, and so the only keys a run reads.
_PARTITION_KEY = re.compile(r"(?:user|chan):[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _derivable_partition_key(value: str | None) -> str | None:
    """Refuse a partition key the runtime never derives.

    Both create dialogs let an editor type the key by hand, and a mistyped one
    would seed a file or fact into a partition no run ever reads - a silent no-op
    answered with a 201 and an audit row. Only `user:<uuid>` and `chan:<uuid>`
    are ever derived, so anything else is a typo and is refused as one.
    """
    if value is not None and _PARTITION_KEY.fullmatch(value) is None:
        raise PydanticCustomError("partition_key", "A partition key is user:<uuid> or chan:<uuid>")
    return value


PartitionKey = Annotated[str | None, AfterValidator(_derivable_partition_key)]


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
    partition_label: str | None = Field(
        default=None,
        description="A readable name for a per-user partition (the member's email), "
        "resolved org-scoped; None for the shared store or a key that does not resolve",
    )
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
    end_user_scope_key: PartitionKey = Field(
        default=None,
        max_length=128,
        description="Which end-user partition to write to - `user:<uuid>` or `chan:<uuid>`; "
        "omit for the shared store",
    )


class AgentMemoryFileUpdate(BaseSchema):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = None
    format: str | None = Field(default=None, min_length=1, max_length=16)
    kind: str | None = Field(default=None, min_length=1, max_length=32)


class AgentMemoryFactCreate(BaseSchema):
    """A fact an operator seeds directly, embedded server-side.

    The one exception to "operators never author facts": seeding standing semantic
    knowledge - a company fact the agent should recall - is a deliberate management
    act. The embedding is metered to the organisation's ingestion spend, the same
    as a RAG document, and the monthly cap is checked before it is spent.
    """

    agent_id: UUID = Field(description="The agent whose memory this fact belongs to")
    content: str = Field(
        min_length=1,
        max_length=2000,
        description="The fact to remember, as a short self-contained sentence",
    )
    end_user_scope_key: PartitionKey = Field(
        default=None,
        max_length=128,
        description="Which end-user partition to write to - `user:<uuid>` or `chan:<uuid>`; "
        "omit for the shared store",
    )


class AgentMemoryFactRead(BaseSchema):
    """One remembered fact, as an operator reviews it.

    There is no update shape - a fact is replaced, not amended - but there is a
    create: an operator may seed one (`AgentMemoryFactCreate`). `origin` is the
    trust tier that decides whether a fact may enter the injected brief, the same
    as a file's. Content is included because a fact is short by nature - the
    listing is the content.
    """

    id: UUID
    agent_id: UUID
    content: str
    origin: MemoryOriginLiteral
    end_user_scope_key: str | None = None
    partition_label: str | None = Field(
        default=None,
        description="A readable name for a per-user partition (the member's email), "
        "resolved org-scoped; None for the shared store or a key that does not resolve",
    )
    created_at: datetime | None = None


class AgentMemoryFactList(BaseSchema):
    items: list[AgentMemoryFactRead]
    total: int
