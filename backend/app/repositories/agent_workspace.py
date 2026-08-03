"""Data access for agent workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_workspace import AgentWorkspace


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


async def list_for_organization(db: AsyncSession, *, organization_id: UUID) -> list[AgentWorkspace]:
    result = await db.execute(
        select(AgentWorkspace)
        .where(AgentWorkspace.organization_id == organization_id)
        .order_by(AgentWorkspace.last_used_at.desc().nullslast())
    )
    return list(result.scalars().all())


async def delete(db: AsyncSession, *, workspace: AgentWorkspace) -> None:
    await db.delete(workspace)
    await db.flush()
