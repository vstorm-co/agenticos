"""Opening the workspace a run works in, and putting it away afterwards.

The capability cannot do this. Opening a workspace reads and writes the database
— loading a stored document, recording which session belongs to which
conversation — and a capability is built inside `build_agent`, which holds no
session and must not acquire one. So the runner opens one here, hands the
backend through `resources`, and closes it in the `finally` that already records
what the run cost.

What "closing" means differs by backend, and the difference is the reason this
module exists rather than a helper on the capability:

* `state` lives in this database. Closing flushes the document, and nothing
  survives that is not flushed.
* `docker` lives in `sandboxd`, which owns its own lifecycle — idle reaping,
  ceilings, hibernation. Closing releases a *run-scoped* session as a courtesy
  and leaves every other scope alone, because correctness must not depend on
  this process getting to its `finally`.
* `daytona` is a cloud resource on the organization's own account, and the same
  applies with somebody else's invoice attached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai_backends import FileInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.sandbox import SandboxConfig
from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.agents.capabilities.sandbox._identity import (
    BackendKind,
    SessionScope,
    WorkspaceIdentity,
    WorkspaceScopeUnavailable,
    scope_key,
)
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent_workspace as workspace_repo
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService

logger = logging.getLogger(__name__)

SANDBOX_CAPABILITY_ID = "sandbox"


@dataclass
class OpenWorkspace:
    """A workspace a run is using, and what it takes to put it away."""

    backend: Any
    kind: BackendKind
    scope: SessionScope
    scope_key: str
    row_id: UUID | None
    """The `agent_workspaces` row, absent only where there is no database to
    write to - a run-scoped workspace, or a spec being exercised by a test."""

    connection_id: UUID | None = None
    """Which registered connection it runs on, for a workspace that is not `state`."""


def sandbox_config(spec: AgentSpec) -> SandboxConfig | None:
    """This spec's workspace configuration, or `None` if it has no workspace.

    Reads the binding rather than being told, so every caller - the runner, the
    publish validator, a route deciding whether a conversation has files - gets
    the same answer from the same place.
    """
    for binding in spec.capabilities:
        if binding.id == SANDBOX_CAPABILITY_ID and binding.enabled:
            return SandboxConfig.model_validate(binding.config)
    return None


class SandboxWorkspaceService:
    """Resolves the backend a run writes to, and persists what it wrote."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.connections = SandboxConnectionService(db)

    async def open(
        self,
        spec: AgentSpec,
        *,
        ctx: AuthContext,
        identity: WorkspaceIdentity,
        scope_override: SessionScope | None = None,
    ) -> OpenWorkspace | None:
        """The workspace this run should use, or `None` when it has no sandbox.

        `scope_override` is what the *exposure* said, when one did. An agent
        reached in web chat and on a Slack bot is the same agent in two
        situations - one has an account and a conversation, the other has a
        channel with threads in it - and one value for both was the wrong shape.
        The spec keeps the default; the binding that admitted this run may narrow
        it.

        Raises:
            BadRequestError: If the spec asks for a backend this deployment
                cannot provide, or a scope this run cannot key. Both are refused
                at publish too; this is the backstop for a spec that was valid
                when it was published and is not any more - a connection deleted
                or switched off, or an agent reached from a surface that has no
                conversation to key a workspace to.
        """
        config = sandbox_config(spec)
        if config is None:
            return None

        scope = scope_override or config.session_scope
        try:
            key = scope_key(identity, scope, config.backend)
        except WorkspaceScopeUnavailable as exc:
            raise BadRequestError(
                message=str(exc),
                details={"session_scope": scope},
            ) from exc

        if config.backend == "state":
            return await self._open_state(config, identity, key, scope)
        return await self._open_service(ctx, config, identity, key, scope)

    async def _open_state(
        self,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
    ) -> OpenWorkspace:
        from pydantic_ai_backends import StateBackend

        row = await self._row(config, identity, key, scope)
        stored = dict(row.files or {}) if row is not None else {}
        backend = CappedStateBackend(
            StateBackend(files=stored),  # type: ignore[arg-type]
            max_bytes=settings.SANDBOX_STATE_MAX_BYTES,
        )
        return OpenWorkspace(
            backend=backend,
            kind="state",
            scope=scope,
            scope_key=key,
            row_id=row.id if row is not None else None,
        )

    async def _open_service(
        self,
        ctx: AuthContext,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
    ) -> OpenWorkspace:
        """A workspace on one of the organization's registered connections.

        Nothing starts here. `RemoteSandbox` opens its session on the first
        operation, so an agent granted a workspace it never touches costs no
        container and not even a round trip.

        The connection is resolved rather than read from settings, which is what
        makes two hosts possible and what keeps the credential in the vault. It
        can fail here for reasons that were fine at publish time - a key rotated
        away, a host switched off - and each says which.
        """
        resolved = await self.connections.resolve(ctx, config.connection_id)
        if resolved.kind == "daytona":
            backend = self._daytona(key, resolved)
        else:
            backend = self._sandboxd(config, identity, key, resolved)

        row = await self._row(
            config, identity, key, scope, session_id=key, connection_id=resolved.row.id
        )
        return OpenWorkspace(
            backend=backend,
            kind="service",
            scope=scope,
            scope_key=key,
            row_id=row.id if row is not None else None,
            connection_id=resolved.row.id,
        )

    @staticmethod
    def _sandboxd(
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        resolved: ResolvedConnection,
    ) -> Any:
        from pydantic_ai_backends.remote import RemoteSandbox

        return RemoteSandbox(
            resolved.row.base_url or "",
            token=resolved.token,
            session_id=key,
            # The spec's alias wins, then the connection's default, then whatever
            # the service itself defaults to. Three levels because each answers a
            # different question: what this agent needs, what this host prefers,
            # and what exists at all.
            runtime=config.runtime or resolved.row.default_runtime,
            # The organization, as a capacity label the service counts against
            # its per-tenant ceiling. It grants nothing - only the service token
            # opens a session at all - and it is what stops one talkative
            # organization occupying the pool of the whole installation.
            tenant=str(identity.organization_id),
            # Every scope but `run` is meant to be returned to, and even `run`
            # reattaches within a turn when two tool calls race to open it.
            reuse=True,
        )

    @staticmethod
    def _daytona(key: str, resolved: ResolvedConnection) -> Any:
        from pydantic_ai_backends import DaytonaSandbox

        # The organization's own key, from the connection, from the vault. Never
        # the SDK's `DAYTONA_API_KEY` fallback, which would put every tenant's
        # sandboxes on whichever account the deployment happens to have set.
        return DaytonaSandbox(api_key=resolved.token, sandbox_id=key)

    async def _row(
        self,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
        *,
        session_id: str | None = None,
        connection_id: UUID | None = None,
    ) -> AgentWorkspace | None:
        """The bookkeeping row for this workspace, created on first use.

        A `run`-scoped workspace gets no row: it is deleted the moment the run
        ends, so a row would be written and removed on every turn to record
        something nothing can outlive.
        """
        if scope == "run":
            return None

        existing = await workspace_repo.get_by_key(
            self.db, organization_id=identity.organization_id, scope_key=key
        )
        if existing is not None:
            return await workspace_repo.touch(self.db, workspace=existing)

        return await workspace_repo.create(
            self.db,
            organization_id=identity.organization_id,
            agent_id=identity.agent_id,
            conversation_id=(identity.conversation_id if scope == "conversation" else None),
            owner_ref=identity.user_id if scope == "user" else None,
            scope=scope,
            scope_key=key,
            backend=config.backend,
            session_id=session_id,
            connection_id=connection_id,
        )

    async def close(self, workspace: OpenWorkspace | None) -> None:
        """Persist or release what the run was using.

        Never raises. This is called from the same `finally` that records the
        run's cost, and an exception here would replace whatever actually
        happened to the run with a storage error.
        """
        if workspace is None:
            return
        try:
            if workspace.kind == "state":
                await self._flush_state(workspace)
            elif workspace.scope == "run":
                await self._release(workspace)
        except Exception:
            logger.exception("workspace_close_failed", extra={"scope_key": workspace.scope_key})

    async def _flush_state(self, workspace: OpenWorkspace) -> None:
        if workspace.row_id is None:
            return
        row = await self.db.get(AgentWorkspace, workspace.row_id)
        if row is None:
            # The conversation was deleted while the run was in flight. The files
            # belonged to it, so there is nothing to keep.
            return
        files = dict(workspace.backend.files)
        await workspace_repo.save_files(
            self.db, workspace=row, files=files, bytes_total=document_size(files)
        )

    async def _release(self, workspace: OpenWorkspace) -> None:
        """Stop a run-scoped sandbox, as a courtesy rather than a guarantee.

        `sandboxd` reaps idle sessions on its own, which is what makes this safe
        to be best-effort: a run that crashes between opening a sandbox and
        getting here leaves one behind for the idle timeout and no longer.
        """
        stop = getattr(workspace.backend, "stop", None)
        if stop is None:
            return
        stop(purge=True)

    async def purge_for_conversation(self, ctx: AuthContext, *, conversation_id: UUID) -> int:
        """Drop every workspace belonging to a conversation being deleted.

        The rows would go with it anyway - `conversation_id` cascades - but a
        container-backed workspace lives outside this database and would sit on
        the host until its TTL swept it, holding files whose conversation the
        user deleted. Only this platform knows the conversation is gone.
        """
        rows = await workspace_repo.list_for_conversation(
            self.db, organization_id=ctx.organization_id, conversation_id=conversation_id
        )
        for row in rows:
            if row.backend != "state" and row.session_id:
                await self._purge_remote(ctx, row)
            await workspace_repo.delete(self.db, workspace=row)
        return len(rows)

    async def _purge_remote(self, ctx: AuthContext, row: AgentWorkspace) -> None:
        if row.connection_id is None:
            return
        from pydantic_ai_backends.remote import RemoteSandbox

        try:
            resolved = await self.connections.resolve(ctx, row.connection_id)
            if resolved.kind != "docker" or not resolved.row.base_url:
                return
            RemoteSandbox(
                resolved.row.base_url,
                token=resolved.token,
                session_id=row.session_id or row.scope_key,
                reuse=True,
            ).stop(purge=True)
        except Exception:
            # A service that is down must not stop a user deleting their chat.
            # The workspace TTL is the net under exactly this.
            logger.warning(
                "workspace_purge_failed", extra={"scope_key": row.scope_key}, exc_info=True
            )

    async def listing(
        self, ctx: AuthContext, *, conversation_id: UUID
    ) -> tuple[AgentWorkspace, list[FileInfo]] | None:
        """The files a conversation's workspace holds, and the row describing it.

        `None` when the conversation has no workspace - it ran an agent without
        one, or the agent's scope is not `conversation`, in which case the files
        are real but are not this conversation's to list.

        No sandbox is started for a container-backed workspace: the files are
        read off the host volume the service keeps, which is what makes browsing
        a conversation from last week cost nothing and work at all after its
        session was reaped.
        """
        rows = await workspace_repo.list_for_conversation(
            self.db, organization_id=ctx.organization_id, conversation_id=conversation_id
        )
        if not rows:
            return None
        row = rows[0]
        return row, await self._entries(ctx, row)

    async def _entries(self, ctx: AuthContext, row: AgentWorkspace) -> list[FileInfo]:
        if row.backend == "state":
            from pydantic_ai_backends import StateBackend

            return list(StateBackend(files=dict(row.files or {})).glob_info("**/*"))
        return await self._remote_entries(ctx, row)

    async def _remote_entries(self, ctx: AuthContext, row: AgentWorkspace) -> list[FileInfo]:
        archive = await self._archive(ctx, row)
        if archive is None:
            return []
        try:
            return list(archive.ls(row.session_id or row.scope_key))
        except Exception:
            # Raised rather than degraded by the archive on purpose: "there are
            # no files" and "the service is misconfigured" must be
            # distinguishable. The route turns this into a 502 rather than an
            # empty folder, because an empty folder is what a user believes.
            logger.warning(
                "workspace_listing_failed", extra={"scope_key": row.scope_key}, exc_info=True
            )
            raise

    async def read_text(self, ctx: AuthContext, *, conversation_id: UUID, path: str) -> str | None:
        """One file's text, or `None` when there is no such workspace or file."""
        found = await self.listing(ctx, conversation_id=conversation_id)
        if found is None:
            return None
        row, _ = found
        if row.backend == "state":
            from pydantic_ai_backends import StateBackend

            backend = StateBackend(files=dict(row.files or {}))
            if not backend.exists(path):
                return None
            return backend.read(path)

        archive = await self._archive(ctx, row)
        if archive is None:
            return None
        return archive.read(row.session_id or row.scope_key, path)

    async def _archive(self, ctx: AuthContext, row: AgentWorkspace) -> Any | None:
        """A reader for the host volume behind a container-backed workspace.

        `None` when the workspace has no connection left to ask - the host was
        forgotten, or this is a Daytona sandbox, which keeps no host volume of
        ours to read. Either way the answer is "no files here", which is true, and
        distinct from the service being misconfigured: that raises.
        """
        if row.connection_id is None:
            return None
        from pydantic_ai_backends.remote import WorkspaceArchive

        resolved = await self.connections.resolve(ctx, row.connection_id)
        if resolved.kind != "docker" or not resolved.row.base_url:
            return None
        return WorkspaceArchive(resolved.row.base_url, token=resolved.token)


def owner_label(row: AgentWorkspace) -> str:
    """Whose workspace this is, for a person looking at a file list.

    Not decoration. Under `agent` scope a user opens a chat and finds a file
    they never created; without a label saying why, the reasonable reading is
    that something leaked.
    """
    if row.scope == "conversation":
        return "This conversation"
    if row.scope == "user":
        return "Your files for this agent"
    if row.scope == "agent":
        return "Shared by everyone who uses this agent"
    return "This run only"
