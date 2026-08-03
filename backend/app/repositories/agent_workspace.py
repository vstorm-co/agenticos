"""Data access for agent workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.conversation import Conversation, Message


async def get_by_key(
    db: AsyncSession, *, organization_id: UUID, scope_key: str
) -> AgentWorkspace | None:
    result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.organization_id == organization_id,
            AgentWorkspace.scope_key == scope_key,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    scope: str,
    scope_key: str,
    backend: str,
    conversation_id: UUID | None = None,
    owner_ref: str | None = None,
    session_id: str | None = None,
    connection_id: UUID | None = None,
    files: dict[str, Any] | None = None,
) -> AgentWorkspace:
    workspace = AgentWorkspace(
        organization_id=organization_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        owner_ref=owner_ref,
        scope=scope,
        scope_key=scope_key,
        backend=backend,
        session_id=session_id,
        connection_id=connection_id,
        files=files,
        bytes_total=0,
        version=0,
        last_used_at=datetime.now(UTC),
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    return workspace


async def save_files(
    db: AsyncSession,
    *,
    workspace: AgentWorkspace,
    files: dict[str, Any],
    bytes_total: int,
) -> AgentWorkspace:
    """Store the document this run produced, bumping the version.

    The version is written unconditionally rather than compared: the caller is a
    `finally` block finishing a run, and refusing to save because somebody else
    saved first would lose the turn's work to protect a turn that already
    finished. The service logs the overlap; see
    :class:`~app.db.models.agent_workspace.AgentWorkspace.version`.
    """
    workspace.files = files
    workspace.bytes_total = bytes_total
    workspace.version += 1
    workspace.last_used_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(workspace)
    return workspace


async def touch(db: AsyncSession, *, workspace: AgentWorkspace) -> AgentWorkspace:
    """Record that a run opened this workspace without changing its files."""
    workspace.last_used_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(workspace)
    return workspace


async def list_for_conversation(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID
) -> list[AgentWorkspace]:
    result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.organization_id == organization_id,
            AgentWorkspace.conversation_id == conversation_id,
        )
    )
    return list(result.scalars().all())


async def get(
    db: AsyncSession, workspace_id: UUID, *, organization_id: UUID
) -> AgentWorkspace | None:
    """One workspace, inside its organization.

    Scoped for the reason every lookup here is: the files in it are whatever
    somebody uploaded to a chat, and an unguessable id is not an access control.
    """
    result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.id == workspace_id,
            AgentWorkspace.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_for_organization(db: AsyncSession, *, organization_id: UUID) -> list[AgentWorkspace]:
    result = await db.execute(
        select(AgentWorkspace)
        .where(AgentWorkspace.organization_id == organization_id)
        .order_by(AgentWorkspace.last_used_at.desc().nullslast())
    )
    return list(result.scalars().all())


async def list_for_reader(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID | None, see_all: bool
) -> list[AgentWorkspace]:
    """The workspaces one person may see, most recently used first.

    `see_all` is for a caller holding `connections:manage` - the permission that
    already decides who may see where sandboxes run, and the honest bar for a
    listing that crosses other people's conversations.

    Everybody else sees the workspaces they are actually part of, and the three
    predicates are the three ways a person reaches one:

    - `owner_ref` matching them, which is a `user`-scoped workspace of their own;
    - a workspace belonging to a conversation of theirs, which covers `conversation`
      scope and the `run` rows that outlive a crash;
    - an `agent`-scoped workspace of an agent they have talked to. Deliberately
      "have talked to" rather than "could open": that scope shares one workspace
      across an agent's users, and the chat panel already shows those files to
      anybody in a conversation with it. Being *able* to open the agent is a wider
      claim, and this listing is not the place to widen it.

    `channel` scope is absent from all three, which is correct rather than an
    oversight: it is keyed on a Slack or Telegram chat, so the people sharing it
    are identified by that platform and not by a row in `users`. It is visible to
    an operator only.
    """
    query = select(AgentWorkspace).where(AgentWorkspace.organization_id == organization_id)
    if not see_all:
        if user_id is None:
            # An anonymous caller is part of no conversation, so the honest answer
            # is nothing at all - never the organization's whole listing.
            return []
        mine = select(Conversation.id).where(Conversation.user_id == user_id)
        # Through `messages`, because a conversation is not had with one agent -
        # the picker can be changed mid-thread, which is why `agent_id` is on the
        # message and not on the conversation.
        my_agents = (
            select(Message.agent_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Message.agent_id.is_not(None))
        )
        query = query.where(
            or_(
                AgentWorkspace.owner_ref == str(user_id),
                AgentWorkspace.conversation_id.in_(mine),
                and_(AgentWorkspace.scope == "agent", AgentWorkspace.agent_id.in_(my_agents)),
            )
        )
    result = await db.execute(query.order_by(AgentWorkspace.last_used_at.desc().nullslast()))
    return list(result.scalars().all())


async def delete(db: AsyncSession, *, workspace: AgentWorkspace) -> None:
    await db.delete(workspace)
    await db.flush()
