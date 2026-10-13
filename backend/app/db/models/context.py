"""Context files - known facts put into a run instead of made to be asked for.

A context file is a piece of an organization's standing knowledge written once
and attached to many agents: a glossary, a brand voice, an escalation matrix, a
list of the products the company sells. It is the database form of the pattern
`clock` is the smallest instance of - structured context injection - and the
`RepoContext` capability in `pydantic-ai-harness` is the reference it ports.

Each file carries a `mode` that decides how it reaches the model:

- `inject` - spliced into the agent's instructions verbatim, so the model simply
  knows it, at the cost of the tokens every run spends on it.
- `link` - left out of the prompt and exposed through a tool, so the model reads
  it only when it decides the file is relevant. The cheaper default for anything
  large or rarely needed.

Content is text: `inject` content becomes prompt, and `link` content is handed
to the model as a string, so a format a model cannot read is a file the agent is
told about and then cannot use. Binary documents belong in a knowledge
collection, which is retrieval, not standing context.

Context files live in the database rather than on disk because they are
*content*, not code: an operator fixes the glossary without a deploy, and two
organizations on one deployment must never see each other's.
"""

import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.models.resource_grant import Visibility


class ContextMode(StrEnum):
    """How a context file reaches the model."""

    INJECT = "inject"
    """Spliced into the agent's instructions verbatim - the model always knows it."""

    LINK = "link"
    """Left out of the prompt and read on demand through a tool."""


class ContextFile(Base, TimestampMixin):
    """One piece of an organization's standing context."""

    __tablename__ = "context_files"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default=Visibility.PRIVATE.value
    )

    # The handle a person and the `link` tool refer to it by. Unique per org so
    # an agent bound to two files cannot end up with an ambiguous reference.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # What the `link` tool shows beside the name so the model can decide whether
    # to read the body without reading it. Unused by `inject`, which has no such
    # decision to inform.
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A hint for how to fence the content when it is injected, and for the editor
    # to render it. Not constrained in the database: it steers presentation, not
    # behaviour, so a value nobody anticipated is harmless where an unknown
    # `mode` would not be.
    format: Mapped[str] = mapped_column(String(16), nullable=False, default="md")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default=ContextMode.INJECT.value)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_context_file_org_name"),
        CheckConstraint(
            "visibility IN ('private', 'team', 'org')", name="ck_context_file_visibility"
        ),
        CheckConstraint("mode IN ('inject', 'link')", name="ck_context_file_mode"),
    )

    def __repr__(self) -> str:
        return f"<ContextFile(org={self.organization_id}, name={self.name}, mode={self.mode})>"
