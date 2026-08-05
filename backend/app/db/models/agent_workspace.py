"""One agent workspace, and who it belongs to.

A workspace is scratch space an agent reads and writes between turns. What makes
it a row rather than a detail of whichever backend holds the files is that the
platform - not the backend - knows the answers to the two questions that matter:
*whose is it*, and *when may it be deleted*.

`sandboxd` sees a session id and a tenant label. It cannot know that the
conversation behind that id was deleted, that the member who owns it left the
organization, or that a dashboard wants to say "conversation X of agent Y"
rather than print a hex string. Parsing those back out of the session id would
make the id a schema, and the first change to it a silent data loss.

For the `state` backend the row is also the storage: `files` is the document
`StateBackend` produces, which is JSON precisely so it can live here. For a
container-backed one it is bookkeeping beside a workspace the service holds, and
`files` stays null.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AgentWorkspace(Base, TimestampMixin):
    """The files an agent keeps, and the identity they are keyed on."""

    __tablename__ = "agent_workspaces"
    __table_args__ = (
        # The scope key already encodes the organization, but the constraint
        # names it anyway: a unique index on the key alone would make a
        # cross-tenant collision a database error instead of an impossibility,
        # and "impossible" is the property worth having.
        UniqueConstraint("organization_id", "scope_key", name="uq_agent_workspace_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """The chat this workspace belongs to, for a conversation-scoped one.

    `CASCADE` rather than `SET NULL`: the files were produced inside that
    conversation and are shown as part of it, so a deleted conversation takes
    them with it. Leaving them orphaned would keep a user's uploads after they
    deleted the thread that held them.
    """

    owner_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    """Whose workspace it is, for a user-scoped one.

    A string rather than a foreign key because not every surface's caller is a
    row in `users` - a Slack member id and a Telegram number are both legitimate
    answers here. Attribution only; the scope key hashes this rather than
    embedding it.
    """

    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False)

    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sandbox_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Which registered connection holds this workspace, when it is not `state`.

    Recorded rather than re-derived, because the questions asked of it later have
    no spec in hand: listing a conversation's files, and purging the sandbox when
    the conversation is deleted. `SET NULL` on purpose - forgetting a host must
    not delete the record of what an agent did on it.
    """

    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The service-side session, for a container-backed workspace.

    Stored so that deleting a conversation can purge the sandbox that belongs to
    it. Equal to `scope_key` today; kept as its own column because what the
    service was told is a fact about the past, and re-deriving it after the key
    format changes would purge the wrong session or none.
    """

    files: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """The `state` backend's document, or null for a backend that holds its own.

    JSONB and not text: it is a JSON document by construction - the library
    stores content that is not valid UTF-8 as base64 for exactly this reason -
    and storing it as a blob would give up every query a dashboard might want.
    """

    bytes_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    """Size of `files`, maintained on write so a cap can be enforced without
    measuring the document on every read."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Bumped on every flush, and compared against on the next one.

    A run loads the document at `open` and stores it at `finish`, so two runs
    holding one workspace is a read-modify-write race and **the last flush wins**.
    That is the accepted behaviour, not an oversight: refusing the write would lose
    a finished turn's work to protect a turn that had already finished, and merging
    two documents needs a rule about what a conflict means that nothing here can
    supply. What this column buys is that the overwrite is *not silent* -
    `SandboxWorkspaceService._flush_state` re-reads the committed row, and logs
    `workspace_flush_overtaken` with the paths it is about to drop.

    Where the race actually happens is worth naming, because it is not where the
    guard is. `agent_session` refuses a second turn on a socket while one is in
    flight, which covers `conversation` scope in web chat - one socket, one turn.
    It covers none of the scopes whose purpose is sharing:

    * `agent` - one workspace across every user of the agent, so two people
      chatting at once are two sockets and two runs.
    * `channel` - a Slack or Telegram chat, where two mentions arrive through the
      router and never touch that guard.
    * `user` - one person on web and on Slack at the same time.

    A real fix is a merge or a lock, and #119's review is where the trade is
    argued. Until then the log is the record, and it names the paths so "a file
    went missing" is answerable.
    """

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AgentWorkspace(id={self.id}, scope={self.scope}, "
            f"backend={self.backend}, key={self.scope_key})>"
        )
