"""Schemas for an agent's memory files and facts.

The operator-facing shape of the `memory` capability. `origin` and `owner_key`
are read-only facts about a row: a person creates trusted (`operator`) rows and
never chooses a row's owner by hand beyond the optional one on create — the
agent's own writes carry `origin="agent"` and an owner derived server-side from
the request.
"""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from app.schemas.base import BaseSchema

MemoryOriginLiteral = Literal["operator", "agent"]

_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
# The shapes `app.core.memory_keys` produces, and so the only owners a run reads.
# A room key ends in a platform chat id, which is the platform's to shape, so it
# is bounded rather than matched: `channel_key` has already stripped the thread.
_OWNER_KEY = re.compile(rf"person:(?:chan:)?{_UUID}|room:[a-z]+:[^\s]{{1,150}}")


def _derivable_owner_key(value: str | None) -> str | None:
    """Refuse an owner key the runtime never derives.

    Both create dialogs let an editor type the key by hand, and a mistyped one
    would seed a file or fact into a store no run ever reads - a silent no-op
    answered with a 201 and an audit row. Only the three shapes
    `app.core.memory_keys` builds are ever derived, so anything else is a typo and
    is refused as one.
    """
    if value is not None and _OWNER_KEY.fullmatch(value) is None:
        raise PydanticCustomError(
            "owner_key",
            "An owner key is person:<uuid>, person:chan:<uuid> or room:<platform>:<chat>",
        )
    return value


OwnerKey = Annotated[str | None, AfterValidator(_derivable_owner_key)]


class AgentMemoryFileRead(BaseSchema):
    id: UUID
    agent_id: UUID
    name: str
    description: str | None = None
    content: str
    format: str
    kind: str
    origin: MemoryOriginLiteral
    # NULL is the organisation's store; `person:…`/`room:…` name one person or one
    # group chat. Raw so an operator can see which store a row is in.
    owner_key: str | None = None
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
    owner_key: str | None = None
    owner_label: str | None = Field(
        default=None,
        description="A readable name for a person's store (the member's email), "
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
        description="How the file is referred to; unique within its store",
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
    owner_key: OwnerKey = Field(
        default=None,
        max_length=200,
        description="Whose memory to write to - `person:<uuid>`, `person:chan:<uuid>` or "
        "`room:<platform>:<chat>`; omit for the organisation's own store",
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
    owner_key: OwnerKey = Field(
        default=None,
        max_length=200,
        description="Whose memory to write to - `person:<uuid>`, `person:chan:<uuid>` or "
        "`room:<platform>:<chat>`; omit for the organisation's own store",
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
    owner_key: str | None = None
    owner_label: str | None = Field(
        default=None,
        description="A readable name for a person's store (the member's email), "
        "resolved org-scoped; None for the shared store or a key that does not resolve",
    )
    created_at: datetime | None = None


class AgentMemoryFactList(BaseSchema):
    items: list[AgentMemoryFactRead]
    total: int
