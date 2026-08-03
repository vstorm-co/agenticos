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
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent as agent_repo
from app.repositories import agent_workspace as workspace_repo
from app.repositories import conversation as conversation_repo
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService

logger = logging.getLogger(__name__)

SANDBOX_CAPABILITY_ID = "sandbox"


@dataclass(frozen=True)
class WorkspaceContents:
    """What a workspace holds, and why that might be less than it holds.

    `unreadable_reason` is part of the answer rather than an exception, because the
    two failures it stands for are not faults: a service configured to keep nothing
    on disk cannot be read without starting a sandbox, and a host that is down will
    be up later. Both used to surface as a 500, which a client can only render as
    "something went wrong" - beside an empty list, which reads as "there are no
    files". Two wrong answers at once.
    """

    entries: list[FileInfo]
    unreadable_reason: str | None = None


@dataclass(frozen=True)
class WorkspaceOverview:
    """One workspace as a table shows it: the row, plus what makes it readable."""

    row: AgentWorkspace
    agent_name: str
    conversation_title: str | None
    conversations: int
    """How many conversations reach these files. Zero for a run-scoped workspace,
    which is gone before anybody could look."""
    access_label: str


@dataclass(frozen=True)
class FlatFileListing:
    """Every file a caller can see, and what the answer left out.

    `truncated` and `unreadable` are carried rather than folded into the list
    because a shorter list is indistinguishable from fewer files, and "an agent is
    not holding that document" is a different answer from "we stopped looking".
    """

    files: list[tuple[WorkspaceOverview, FileInfo]]
    workspaces_read: int
    unreadable: int
    truncated: bool


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

    async def visible_to(self, ctx: AuthContext) -> list[WorkspaceOverview]:
        """The workspaces this caller may see, with what a table needs beside each.

        Scoped in the query rather than gated on the route. An operator holding
        `connections:manage` sees the organization's; everybody else sees the ones
        they are part of - their own `user`-scoped files, the workspaces of their
        own conversations, and the shared workspace of an agent they have talked
        to. A route gate would have refused a member entirely, which is what made
        this an operator screen and left a person no way to see the files an agent
        was keeping *for them*.

        Rows only, no files: a deployment can hold a workspace per warm
        conversation, and reading each would be a query or a round trip per row
        for a page nobody has asked a question of yet.

        Everything a table needs is resolved here in three grouped queries rather
        than per row - the agent's name, the linked conversation's title, and how
        many conversations reach the files - because the alternative is a client
        that fetches agents and conversations to make a table of hex ids readable.
        """
        rows = await workspace_repo.list_for_reader(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            see_all=self._sees_every_workspace(ctx),
        )
        if not rows:
            return []
        agents = await agent_repo.get_many(
            self.db, [row.agent_id for row in rows], organization_id=ctx.organization_id
        )
        titles = await conversation_repo.titles_for(
            self.db,
            [row.conversation_id for row in rows if row.conversation_id is not None],
            organization_id=ctx.organization_id,
        )
        # Only for the scopes where more than one chat reaches one workspace. A
        # conversation-scoped workspace has exactly one by construction, and
        # counting it would be a query answering a question nobody asked.
        shared = {row.agent_id for row in rows if row.scope in ("agent", "channel")}
        counts = (
            await conversation_repo.count_by_agent(
                self.db, list(shared), organization_id=ctx.organization_id
            )
            if shared
            else {}
        )
        return [
            WorkspaceOverview(
                row=row,
                agent_name=(
                    agents[row.agent_id].name if row.agent_id in agents else "a deleted agent"
                ),
                conversation_title=(
                    None if row.conversation_id is None else titles.get(row.conversation_id)
                ),
                conversations=(
                    1
                    if row.conversation_id is not None
                    else counts.get(row.agent_id, 0)
                    if row.scope in ("agent", "channel")
                    else 0
                ),
                access_label=access_label(row),
            )
            for row in rows
        ]

    @staticmethod
    def _sees_every_workspace(ctx: AuthContext) -> bool:
        """Whether this caller reads across other people's conversations.

        `connections:manage` and nothing else. It is the permission that already
        decides who may see where sandboxes run, and listing every workspace means
        listing files from chats belonging to people who are not the caller - so
        the bar is the operator's, not a member's.
        """
        return ctx.has(Perm.CONNECTIONS_MANAGE)

    async def flat_files(self, ctx: AuthContext, *, limit: int = 25) -> FlatFileListing:
        """Every file this caller can see, in one list, with its workspace named.

        The "which agent is holding a copy of that CSV" view. Asking it of the
        listing above means opening each workspace in turn, which is the question
        this answers in one call instead.

        Bounded, and the bound is reported rather than silently applied: reading a
        container-backed workspace is a round trip to its host, so twenty-five of
        them is already a slow request and two hundred would be a page that times
        out. `truncated` says the answer is partial, which a listing that quietly
        stopped could not.

        A workspace that cannot be read is skipped and counted rather than dropping
        the request: one unreachable host must not empty a list that is mostly
        readable, and `unreadable` is what stops the shorter list reading as fewer
        files.
        """
        overviews = await self.visible_to(ctx)
        files: list[tuple[WorkspaceOverview, FileInfo]] = []
        unreadable = 0
        for overview in overviews[:limit]:
            contents = await self._entries(ctx, overview.row)
            if contents.unreadable_reason is not None:
                unreadable += 1
                continue
            files.extend((overview, entry) for entry in contents.entries if not entry.get("is_dir"))
        return FlatFileListing(
            files=files,
            workspaces_read=min(len(overviews), limit) - unreadable,
            unreadable=unreadable,
            truncated=len(overviews) > limit,
        )

    async def files_of(
        self, ctx: AuthContext, workspace_id: UUID
    ) -> tuple[AgentWorkspace, WorkspaceContents]:
        """One workspace's files, addressed by its own id.

        The sibling of :meth:`listing`, which addresses a workspace through the
        conversation that owns it. Both exist because they answer different
        questions: a chat asks "what is in *this* thread", and an operator
        browsing every workspace has a row in hand and no conversation at all -
        a `run`-scoped one never had one, and an `agent`-scoped one belongs to
        all of them.

        Raises:
            NotFoundError: If it is not this organization's, or not one this
                caller may see. Reported as missing rather than refused in both
                cases, so an id cannot be used to find out which workspaces exist
                - in another organization, or in a colleague's conversation.
        """
        row = await workspace_repo.get(self.db, workspace_id, organization_id=ctx.organization_id)
        if row is None or not await self._may_read(ctx, row):
            raise NotFoundError(
                message="Workspace not found", details={"workspace_id": str(workspace_id)}
            )
        return row, await self._entries(ctx, row)

    async def _may_read(self, ctx: AuthContext, row: AgentWorkspace) -> bool:
        """Whether this caller reaches one workspace by id.

        The same three predicates the listing applies, asked of one row - and asked
        here rather than only there, because a listing that hides a row and a route
        that serves it by id is not access control. The query is reused rather than
        reimplemented for exactly that reason: two copies of "who can see this"
        disagree eventually, and the one that is wrong is the one nobody reads.
        """
        if self._sees_every_workspace(ctx):
            return True
        visible = await workspace_repo.list_for_reader(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            see_all=False,
        )
        return any(candidate.id == row.id for candidate in visible)

    async def read_bytes_of(self, ctx: AuthContext, workspace_id: UUID, *, path: str) -> bytes:
        """One file as bytes, for a download or an image preview.

        Bytes rather than text because the two are not interchangeable for the files
        an agent actually produces: a PNG decoded as UTF-8 and re-encoded is a
        corrupt PNG, and a chart is the commonest thing in a workspace nobody can
        read as a string.

        Only a stored workspace can answer that faithfully. A container-backed one
        is read through `WorkspaceArchive`, whose only reader is textual - so a text
        file is served by encoding it, and anything else is refused rather than
        quietly mangled. `vstorm-co/pydantic-ai-backend` is where a byte-range
        reader belongs; guessing one here would mean this platform re-implementing
        the archive protocol.

        Raises:
            NotFoundError: If the workspace is not this caller's, or holds no such
                file.
            BadRequestError: If the host cannot be read, or cannot serve this file
                as bytes.
        """
        row, contents = await self.files_of(ctx, workspace_id)
        # Answered from the listing rather than from the read that follows. A
        # container-backed host raises the same way for "no such file" as for "this
        # host cannot be read", so without this a missing file is reported as a
        # configuration problem - and 400 is the wrong answer to a typo in a path.
        if _absent(row, contents, path):
            raise NotFoundError(
                message="No such file",
                details={"workspace_id": str(workspace_id), "path": path},
            )
        if row.backend == "state":
            from pydantic_ai_backends import StateBackend

            backend = StateBackend(files=dict(row.files or {}))
            if not backend.exists(path):
                raise NotFoundError(
                    message="No such file",
                    details={"workspace_id": str(workspace_id), "path": path},
                )
            return backend.read_bytes(path)

        if not _is_textual(path):
            raise BadRequestError(
                message=(
                    "This host keeps its files in a container, and the workspace "
                    "archive can only read text - so this file cannot be downloaded "
                    "from here. A stored workspace serves any file."
                ),
                details={"workspace_id": str(workspace_id), "path": path},
            )
        text = await self._read_from(ctx, row, path)
        if text is None:
            raise NotFoundError(
                message="No such file", details={"workspace_id": str(workspace_id), "path": path}
            )
        return text.encode()

    async def read_file_of(self, ctx: AuthContext, workspace_id: UUID, *, path: str) -> str | None:
        """One file's text from a workspace addressed by its own id."""
        row, contents = await self.files_of(ctx, workspace_id)
        if _absent(row, contents, path):
            return None
        return await self._read_from(ctx, row, path)

    async def listing(
        self, ctx: AuthContext, *, conversation_id: UUID
    ) -> tuple[AgentWorkspace, WorkspaceContents] | None:
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

    async def _entries(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        if row.backend == "state":
            return WorkspaceContents(entries=stored_entries(dict(row.files or {})))
        return await self._remote_entries(ctx, row)

    async def _remote_entries(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        try:
            archive = await self._archive(ctx, row)
            if archive is None:
                return WorkspaceContents(entries=[])
            return WorkspaceContents(entries=list(archive.ls(row.session_id or row.scope_key)))
        except Exception as exc:
            # Carried, not raised. "There are no files" and "this host cannot be
            # read" must stay distinguishable - an empty folder is what a user
            # believes - but a 500 said neither: the panel showed a red "an
            # unexpected error occurred" beside "nothing yet", which is two wrong
            # answers at once.
            #
            # The commonest cause is not a fault at all. A service started with no
            # `workspace_root` keeps nothing on disk, so files exist only while a
            # sandbox is running, and reading them without starting one is
            # impossible by construction. That is a sentence for an operator, and
            # the service's own detail names the setting - so it is passed through
            # rather than replaced with something vaguer.
            #
            # Resolving the connection is inside the same `try` deliberately: a
            # host retired or a credential rotated away raises there, and it is the
            # same class of answer - these files cannot be read right now, and here
            # is why.
            logger.warning(
                "workspace_listing_failed", extra={"scope_key": row.scope_key}, exc_info=True
            )
            return WorkspaceContents(entries=[], unreadable_reason=_reason(exc))

    async def read_text(self, ctx: AuthContext, *, conversation_id: UUID, path: str) -> str | None:
        """One file's text, or `None` when there is no such workspace or file."""
        found = await self.listing(ctx, conversation_id=conversation_id)
        if found is None:
            return None
        row, _ = found
        return await self._read_from(ctx, row, path)

    async def _read_from(self, ctx: AuthContext, row: AgentWorkspace, path: str) -> str | None:
        """One file out of one workspace, whichever backend holds it.

        Shared by the two ways a workspace is addressed - through its conversation
        and by its own id - so a path that is refused one way cannot be readable
        the other.
        """
        if row.backend == "state":
            from pydantic_ai_backends import StateBackend

            backend = StateBackend(files=dict(row.files or {}))
            if not backend.exists(path):
                return None
            return backend.read(path)

        archive = await self._archive(ctx, row)
        if archive is None:
            return None
        try:
            return archive.read(row.session_id or row.scope_key, path)
        except Exception as exc:
            # A 400 naming the reason, rather than the 500 this used to be or the
            # 404 that "no such file" would have been. Both of those tell somebody
            # the file is missing when the truth is that this host cannot serve it.
            raise BadRequestError(
                message=_reason(exc), details={"workspace_id": str(row.id), "path": path}
            ) from exc

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


TEXTUAL_SUFFIXES = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".log",
        ".sql",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".xml",
        ".svg",
        ".sh",
        ".bash",
        ".zsh",
        ".rs",
        ".go",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".patch",
        ".diff",
    }
)
"""Suffixes a text-only reader can serve without corrupting the file.

An allowlist rather than a guess at the bytes: the question being answered is "may
this be read as a string", and a file with no suffix or an unknown one is exactly
the case where guessing wrong is silent. `.svg` is here because it *is* text -
whether it may be *displayed* inline is a separate decision the route makes, and
the answer there is no.
"""


def _absent(row: AgentWorkspace, contents: WorkspaceContents, path: str) -> bool:
    """Whether a listing that could be read says this path is not in it.

    Only asked of a workspace kept on a host. A stored one has an authoritative
    oracle - `StateBackend.exists` - and using a *listing* as one there is wrong:
    `glob_info` does not match dotfiles, so `/​.env` exists, reads fine, and is not
    in any listing. Answering "no such file" for it would be a confident wrong
    answer built on a pattern's blind spot.

    An unreadable listing also answers `False`: it knows nothing, and the same
    argument applies.
    """
    if row.backend == "state":
        return False
    if contents.unreadable_reason is not None or not contents.entries:
        return False
    return all(str(entry.get("path")) != path for entry in contents.entries)


def _is_textual(path: str) -> bool:
    from pathlib import PurePosixPath

    return PurePosixPath(path).suffix.lower() in TEXTUAL_SUFFIXES


def stored_entries(files: dict[str, Any]) -> list[FileInfo]:
    """Every file in a stored workspace, dotfiles included.

    Two patterns, because one is not enough: `**/*` does not match a name beginning
    with a dot, so an agent that wrote `/​.env` or `/​.gitignore` had it absent from
    every listing - the chat panel, the browser, the flat view - while `read` served
    it happily. A listing that claims to be "what the agent is keeping" cannot quietly
    omit a class of filename.

    A file *inside* a dot-directory (`/​.git/config`) is still absent, and that is the
    one omission worth keeping: an agent that ran `git init` would otherwise fill the
    panel with object files nobody asked to see.
    """
    from pydantic_ai_backends import StateBackend

    backend = StateBackend(files=files)
    seen: dict[str, FileInfo] = {}
    for pattern in ("**/*", "**/.*"):
        for entry in backend.glob_info(pattern):
            seen[str(entry.get("path"))] = entry
    return sorted(seen.values(), key=lambda entry: str(entry.get("path")))


def _reason(exc: Exception) -> str:
    """Why a host's files could not be read, in a sentence a client can show.

    The service's own detail is kept rather than replaced: for the commonest cause
    it names the exact setting (`workspace_root`), which is the difference between
    an operator fixing this in one line and filing a bug against us.
    """
    detail = str(exc).strip() or exc.__class__.__name__
    return f"This host's files could not be read. {detail}"


def access_label(row: AgentWorkspace) -> str:
    """Who can see these files, said in words rather than as a scope name.

    `scope` is the mechanism; this is the consequence, and they are not the same
    sentence. "agent" tells an operator nothing about whether the file they are
    looking at is one person's or the whole team's - which is the question somebody
    auditing a workspace is actually asking.
    """
    if row.scope == "conversation":
        return "Whoever is in that conversation"
    if row.scope == "user":
        return "One person, in this agent only"
    if row.scope == "agent":
        return "Everybody who talks to this agent"
    if row.scope == "channel":
        return "Everybody in that chat"
    return "Nobody - it is deleted when the run ends"


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
