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

import asyncio
import base64
import logging
import shlex
from binascii import Error as BinasciiError
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from PIL import Image, ImageOps
from pydantic_ai_backends import FileData, FileInfo
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
from app.agents.capabilities.tool_output_limits import OVERFLOW_PREFIX
from app.agents.spec import AgentSpec
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_workspace import AgentWorkspace
from app.repositories import agent as agent_repo
from app.repositories import agent_workspace as workspace_repo
from app.repositories import conversation as conversation_repo
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_runtimes import runtime_briefing

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
    agent_has_avatar: bool
    """Whether the agent has a face to draw - resolved here because the reader
    of this listing may not hold `agents:view` to ask the agent list."""
    conversation_title: str | None
    conversation_is_callers: bool
    """Whether the linked conversation belongs to the caller. The chat page
    lists its owner's threads, so a link is only honest for the owner."""
    conversations: int
    """How many conversations reach these files. Zero for a run-scoped workspace,
    which is gone before anybody could look."""
    access_label: str


@dataclass(frozen=True)
class MeasuredWorkspaces:
    """File counts and byte totals for a listing, and what it cost to get them."""

    counts: dict[UUID, tuple[int, int]]
    """Workspace id to `(files, bytes)`. Absent for one that was not read."""

    measured: int
    unreadable: int
    truncated: bool


@dataclass(frozen=True)
class FlatEntry:
    """One file in the flat view, with everything its tile draws.

    Both hints are `None` for a container-backed workspace, whose bytes live on a
    host this listing deliberately does not visit per file - the whole point of the
    bound in :meth:`WorkspaceService.flat_files`.
    """

    overview: WorkspaceOverview
    info: FileInfo
    preview: str | None
    """The first lines of a stored text file. `None` for binary content."""
    thumbnail: str | None
    """A stored image, scaled down to a data URI. `None` for anything else."""


@dataclass(frozen=True)
class FlatFileListing:
    """Every file a caller can see, and what the answer left out.

    `truncated` and `unreadable` are carried rather than folded into the list
    because a shorter list is indistinguishable from fewer files, and "an agent is
    not holding that document" is a different answer from "we stopped looking".
    """

    files: list[FlatEntry]
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

    briefing: str | None = None
    """What this run should tell its model about the container it works in.

    Composed here rather than carried as an alias, because an alias would be
    `None` for two different reasons - no `sandboxd` at all, and a `sandboxd`
    whose default nobody overrode - and only the second one is describable.
    `None` for a `state` or Daytona workspace, whose image this deployment does
    not build and so cannot honestly describe.
    """

    opened_version: int | None = None
    """What `version` said when this run loaded the document.

    Carried so the flush can tell whether somebody else stored one in between.
    `None` where there is no row to compare against - a run-scoped workspace, or a
    container-backed one, which keeps its files on the host rather than here.
    """

    spills: list[str] = field(default_factory=list)
    """Every spill handle `tool_output_limits` wrote to this workspace this run.

    Registered beside the backend under `SPILL_LOG_RESOURCE`, appended by the
    overflow store, and read back by `close`: a container-backed workspace whose
    scope outlives the run deletes exactly these paths, so a spill never survives
    the run that produced it (#803). Exact handles rather than the `tool_output/`
    prefix, because concurrent runs share a longer-scoped workspace and a prefix
    sweep would take another run's spills mid-flight.
    """


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


def _without_spills(files: dict[str, FileData]) -> dict[str, FileData]:
    """The workspace document with `tool_output_limits` spills stripped out (#803).

    A spilled tool return goes to the run's backend under the reserved
    `tool_output/` prefix so `read_tool_result` can page through it, but it is a
    within-run artefact and must never survive into the persisted document. On a
    longer-scoped state workspace it otherwise accumulates every run and counts
    against `SANDBOX_STATE_MAX_BYTES`, until the cap starts refusing the agent's
    own writes. Stripping it at flush keeps the invariant "the stored document
    holds the agent's files, never its spills", every run self-healing whatever a
    prior one left. Backend keys are normalized with a leading slash; the
    `lstrip` tolerates both forms.
    """

    def _is_spill(path: str) -> bool:
        relative = path.lstrip("/")
        return relative == OVERFLOW_PREFIX or relative.startswith(f"{OVERFLOW_PREFIX}/")

    return {path: data for path, data in files.items() if not _is_spill(path)}


def _under_overflow(path: str) -> bool:
    """Whether this path is a file inside the reserved spill directory.

    The delete in `_prune_spills` runs a shell command over paths from a list, so
    even though only the overflow store appends to that list, every path is checked
    against the one invariant that makes the command safe: it removes spills and
    nothing else. Depth-agnostic because a backend normalizes handles its own way -
    `/tool_output/…` from `state`, an absolute in-container `/workspace/tool_output/…`
    from a service. The prefix must be a proper ancestor (`parts[:-1]`), which is
    what every handle the store writes has, and what guarantees `_overflow_parents`
    answers at least the spill directory itself. A `..` component is refused
    outright: `PurePosixPath` does not resolve one, so `tool_output/../x` would
    pass the ancestor check while naming a file outside the spill directory.
    """
    parts = PurePosixPath(path).parts
    return ".." not in parts and OVERFLOW_PREFIX in parts[:-1]


def _overflow_parents(handle: str) -> list[str]:
    """The directories above a spill handle, up to and including `tool_output/`.

    What `rmdir` is offered once the files are gone, so a pruned run leaves no empty
    run-directory behind. Ancestors above the reserved prefix are not returned:
    the workspace root is not this function's to offer for deletion.
    """
    parents = []
    current = PurePosixPath(handle).parent
    while OVERFLOW_PREFIX in current.parts:
        parents.append(str(current))
        current = current.parent
    return parents


class SandboxWorkspaceService:
    """Resolves the backend a run writes to, and persists what it wrote."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.connections = SandboxConnectionService(db)
        self._connections_by_id: dict[UUID, ResolvedConnection] = {}

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
        if config.backend == "state":
            return await self._open_state(
                config, identity, self._key(identity, scope, "state"), scope
            )

        # The scope is checked before the connection is resolved, so an agent
        # reached from a surface it cannot be keyed on says so rather than
        # reporting whatever is wrong with a host it was never going to use.
        self._key(identity, scope, "service")
        # Then resolved *before* the real key, because which host this runs on
        # belongs in the key - see `scope_key`. Two connections are two
        # workspaces, so a moved agent opens a new one instead of reattaching to
        # a row that names the host it has left.
        resolved = await self.connections.resolve(ctx, config.connection_id)
        key = self._key(identity, scope, "service", resolved.row.id)
        return await self._open_service(config, identity, key, scope, resolved)

    @staticmethod
    def _key(
        identity: WorkspaceIdentity,
        scope: SessionScope,
        backend: BackendKind,
        connection_id: UUID | None = None,
    ) -> str:
        """`scope_key`, with the one failure it has turned into an HTTP answer."""
        try:
            return scope_key(identity, scope, backend, connection_id)
        except WorkspaceScopeUnavailable as exc:
            raise BadRequestError(
                message=str(exc),
                details={"session_scope": scope},
            ) from exc

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
            opened_version=row.version if row is not None else None,
        )

    async def _open_service(
        self,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
        resolved: ResolvedConnection,
    ) -> OpenWorkspace:
        """A workspace on one of the organization's registered connections.

        Nothing starts here. `RemoteSandbox` opens its session on the first
        operation, so an agent granted a workspace it never touches costs no
        container and not even a round trip.

        The connection arrives resolved rather than being read from settings,
        which is what makes two hosts possible and what keeps the credential in
        the vault. It is resolved by the caller because the key depends on it -
        resolving can fail for reasons that were fine at publish time (a key
        rotated away, a host switched off) and each of those says which.
        """
        briefing: str | None = None
        if resolved.kind == "daytona":
            backend = self._daytona(key, resolved)
        else:
            backend = self._sandboxd(config, identity, key, resolved)
            briefing = runtime_briefing(config.runtime or resolved.row.default_runtime or None)

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
            briefing=briefing,
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
            else:
                await self._prune_spills(workspace)
        except Exception:
            logger.exception("workspace_close_failed", extra={"scope_key": workspace.scope_key})

    async def _flush_state(self, workspace: OpenWorkspace) -> None:
        # `populate_existing`, so this is a read of what is *committed* rather than
        # of what this session loaded at `open`. Without it the identity map answers
        # with the row as it was, and a flush by another run - another person under
        # `agent` scope, the same person on a second surface - is invisible by
        # construction. One SELECT per finish is what the detection below costs.
        row = (
            None
            if workspace.row_id is None
            else await self.db.get(AgentWorkspace, workspace.row_id, populate_existing=True)
        )
        if row is None:
            # The conversation was deleted while the run was in flight. The files
            # belonged to it, so there is nothing to keep.
            return
        self._warn_if_overtaken(workspace, row)
        files = _without_spills(workspace.backend.files)
        await workspace_repo.save_files(
            self.db, workspace=row, files=files, bytes_total=document_size(files)
        )

    @staticmethod
    def _warn_if_overtaken(workspace: OpenWorkspace, row: AgentWorkspace) -> None:
        """Say so when this flush is about to overwrite somebody else's.

        The write still happens - see `save_files` for why refusing it would lose
        the finished turn's work to protect a turn that already finished - so this
        is the whole of the mechanism, and without it the overwrite was silent.

        The paths it lost are named rather than counted. "A file went missing" is
        the report that arrives, and the only thing that makes it actionable is
        knowing which file and which two workspaces.
        """
        opened = workspace.opened_version
        if opened is None or row.version == opened:
            return
        overwritten = sorted(set(row.files or {}) - set(workspace.backend.files))
        logger.warning(
            "workspace_flush_overtaken",
            extra={
                "scope_key": workspace.scope_key,
                "scope": workspace.scope,
                "opened_version": opened,
                "found_version": row.version,
                "paths_lost": overwritten,
            },
        )

    async def _prune_spills(self, workspace: OpenWorkspace) -> None:
        """Delete this run's spilled tool returns off a workspace that outlives it.

        The container-backed half of #803: a `state` workspace has its spills
        stripped at flush and a `run`-scoped container dies purged, but a
        `conversation`/`user`/`agent`-scoped container keeps its filesystem across
        runs, so the spills this run wrote are removed here, by the exact handles
        the overflow store recorded. Another run's spills are untouched - its
        handles are in its own workspace's list.

        Deleted through the backend's own `execute`, because the backend protocol
        has no delete and growing one belongs upstream. The `rmdir` afterwards
        clears the now-empty run directories; it fails silently where a concurrent
        run still keeps files, which is the correct answer - which is why the
        command exits with `rm`'s status, captured before the `rmdir`: a refused
        `rm` is the failure the warning below exists for, and a trailing cleanup
        must not mask it as success. Best-effort like `_release`: a run that
        crashes before its `finally` leaves its spills for the next manual sweep,
        and `close` already logs whatever raises here.
        """
        handles = [handle for handle in workspace.spills if _under_overflow(handle)]
        if not handles:
            return
        execute = getattr(workspace.backend, "execute", None)
        if execute is None:
            return
        directories = sorted(
            {parent for handle in handles for parent in _overflow_parents(handle)},
            key=lambda directory: directory.count("/"),
            reverse=True,
        )
        files = " ".join(shlex.quote(handle) for handle in handles)
        emptied = " ".join(shlex.quote(directory) for directory in directories)
        command = f"rm -f -- {files}; status=$?; rmdir -- {emptied} 2>/dev/null; exit $status"
        result = await asyncio.to_thread(execute, command)
        if getattr(result, "exit_code", 0) != 0:
            logger.warning(
                "workspace_spill_prune_failed",
                extra={
                    "scope_key": workspace.scope_key,
                    "handles": len(handles),
                    "output": getattr(result, "output", ""),
                },
            )

    async def _release(self, workspace: OpenWorkspace) -> None:
        """Stop a run-scoped sandbox, as a courtesy rather than a guarantee.

        `sandboxd` reaps idle sessions on its own, which is what makes this safe
        to be best-effort for a container: a run that crashes between opening a
        sandbox and getting here leaves one behind for the idle timeout and no
        longer.

        A Daytona sandbox has no such net. It is a cloud resource on the
        organization's own account, so the courtesy is the only thing that ends
        it, which is why the call has to actually land.
        """
        stop = getattr(workspace.backend, "stop", None)
        if stop is None:
            return
        # One signature across every backend as of pydantic-ai-backend 0.2.25
        # (vstorm-co/pydantic-ai-backend#98). Before it, `RemoteSandbox.stop` took
        # `purge` and `DaytonaSandbox.stop` took nothing, so this call raised a
        # `TypeError` that `close` swallowed as `workspace_close_failed` - and the
        # one backend with no idle reaper behind it was the one never released, a
        # sandbox per run on somebody's invoice. An `inspect.signature` check stood
        # here until the library stopped needing one.
        #
        # Off the loop: both are synchronous HTTP to somebody else.
        await asyncio.to_thread(stop, purge=True)

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
        """Delete the sandbox behind a workspace whose conversation is going.

        Both kinds are reached, and the cloud one matters more. A container has
        `sandboxd`'s TTL behind it, so failing here costs a host some disk until
        it sweeps. A Daytona sandbox has nothing behind it: this platform is the
        only thing that knows the conversation is gone, and the organization pays
        for the sandbox until somebody deletes it. This used to return early for
        anything that was not Docker, so that was never.
        """
        if row.connection_id is None:
            return

        try:
            resolved = await self._connection(ctx, row.connection_id)
            if resolved.kind == "daytona":
                from pydantic_ai_backends import DaytonaSandbox

                # The organization's own key, as everywhere else - never the SDK's
                # `DAYTONA_API_KEY` fallback. `purge` is accepted and makes no
                # difference here: Daytona has no "end it but keep the files" state,
                # so stopping is deleting. Passed anyway, because this call site is
                # about discarding the conversation's workspace and saying so is
                # better than relying on the default meaning the same thing.
                cloud = DaytonaSandbox(
                    api_key=resolved.token, sandbox_id=row.session_id or row.scope_key
                )
                await asyncio.to_thread(cloud.stop, purge=True)
                return

            from pydantic_ai_backends.remote import RemoteSandbox

            # Only the address is checked. The kind used to be too, which is how
            # Daytona fell through here and was never purged at all; now that it
            # returns above, `docker` is the only kind left - a connection is one
            # or the other - and an address it has no value for is the one thing
            # still worth refusing, because `RemoteSandbox("")` would post the
            # organization's token at whatever a relative URL resolves to.
            if not resolved.row.base_url:
                return
            sandbox = RemoteSandbox(
                resolved.row.base_url,
                token=resolved.token,
                session_id=row.session_id or row.scope_key,
                reuse=True,
            )
            # A synchronous `DELETE`, so off the loop - and this runs in a loop over
            # every workspace the conversation held, which is where one blocking
            # round trip becomes several.
            await asyncio.to_thread(sandbox.stop, purge=True)
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
                agent_has_avatar=(
                    agents[row.agent_id].has_avatar if row.agent_id in agents else False
                ),
                conversation_title=(
                    None
                    if row.conversation_id is None
                    else (head.title if (head := titles.get(row.conversation_id)) else None)
                ),
                conversation_is_callers=(
                    row.conversation_id is not None
                    and (owner := titles.get(row.conversation_id)) is not None
                    and owner.user_id is not None
                    and owner.user_id == ctx.user_id
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

    async def measured(
        self, ctx: AuthContext, overviews: list[WorkspaceOverview], *, hosts: bool, limit: int = 25
    ) -> MeasuredWorkspaces:
        """How many files each workspace holds, and what they come to.

        Free for a stored workspace: its files are a column of the row this listing
        already read, so the count is arithmetic. A container's are on its host, and
        reading them is a round trip *per workspace* - the cost `flat_files` bounds
        at twenty-five and reports rather than pays silently. So `hosts` is the
        caller's decision and the default listing does not make it.

        A workspace whose host will not answer is counted, not dropped: a listing
        that quietly skipped it would read as a workspace holding no files, which is
        the one answer nobody can distinguish from the truth.
        """
        counts: dict[UUID, tuple[int, int]] = {}
        unreadable = 0
        read = 0
        remote = 0
        for overview in overviews:
            row = overview.row
            if row.backend != "state":
                if not hosts:
                    continue
                if remote >= limit:
                    continue
                remote += 1
            contents = await self._entries(ctx, row)
            if contents.unreadable_reason is not None:
                unreadable += 1
                continue
            files = [entry for entry in contents.entries if not entry.get("is_dir")]
            counts[row.id] = (
                len(files),
                sum(int(entry.get("size") or 0) for entry in files),
            )
            read += 1
        containers = sum(1 for overview in overviews if overview.row.backend != "state")
        return MeasuredWorkspaces(
            counts=counts,
            measured=read,
            unreadable=unreadable,
            truncated=hosts and containers > limit,
        )

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
        files: list[FlatEntry] = []
        unreadable = 0
        for overview in overviews[:limit]:
            contents = await self._entries(ctx, overview.row)
            if contents.unreadable_reason is not None:
                unreadable += 1
                continue
            stored = dict(overview.row.files or {}) if overview.row.backend == "state" else {}
            files.extend(
                FlatEntry(
                    overview=overview,
                    info=entry,
                    preview=stored_preview(stored.get(str(entry.get("path")))),
                    thumbnail=stored_thumbnail(
                        str(entry.get("path")), stored.get(str(entry.get("path")))
                    ),
                )
                for entry in contents.entries
                if not entry.get("is_dir")
            )
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
        return await self._bytes_from(ctx, row, contents, path)

    async def read_bytes(self, ctx: AuthContext, *, conversation_id: UUID, path: str) -> bytes:
        """One file as bytes, addressed through the conversation that holds it.

        The sibling of :meth:`read_bytes_of`, and both exist for the reason the two
        listings do: the route above this one authorises by fetching the
        conversation, which somebody a chat was *shared with* passes and
        `_may_read` does not - it matches conversations a caller owns. Sending the
        chat panel at the id-addressed route instead would have shown a share
        recipient files it then refused to open.

        Raises:
            NotFoundError: If the conversation keeps no workspace, or it holds no
                such file.
            BadRequestError: If the host cannot be read, or cannot serve this file
                as bytes.
        """
        found = await self.listing(ctx, conversation_id=conversation_id)
        if found is None:
            raise NotFoundError(
                message="This conversation keeps no files",
                details={"conversation_id": str(conversation_id)},
            )
        row, contents = found
        return await self._bytes_from(ctx, row, contents, path)

    async def _bytes_from(
        self, ctx: AuthContext, row: AgentWorkspace, contents: WorkspaceContents, path: str
    ) -> bytes:
        """One file's bytes out of a workspace already resolved and authorised.

        Shared by the two ways a workspace is addressed, so a file that downloads
        one way cannot be refused the other.

        Both backends serve any file now. A container-backed one used to serve only
        text and refuse the rest by suffix, because `WorkspaceArchive` could only
        `read` - which meant the backend you would use for real work was the one
        whose charts and PDFs could not be fetched. `read_bytes` arrived in
        pydantic-ai-backend 0.2.25 (vstorm-co/pydantic-ai-backend#96) and the
        allowlist went with it.
        """
        details = {"workspace_id": str(row.id), "path": path}
        # Answered from the listing rather than from the read that follows. A
        # container-backed host raises the same way for "no such file" as for "this
        # host cannot be read", so without this a missing file is reported as a
        # configuration problem - and 400 is the wrong answer to a typo in a path.
        if _absent(row, contents, path):
            raise NotFoundError(message="No such file", details=details)
        if row.backend == "state":
            state = self._state_bytes(row, path)
            if state is None:
                raise NotFoundError(message="No such file", details=details)
            return state

        raw = await self._read_bytes_from(ctx, row, path)
        if raw is None:
            raise NotFoundError(message="No such file", details=details)
        return raw

    async def _read_bytes_from(
        self, ctx: AuthContext, row: AgentWorkspace, path: str
    ) -> bytes | None:
        """One file's bytes off a container-backed host's volume.

        What `_read_from` is built on rather than its sibling, which is the way round
        it ended up: bytes are what the host holds, and text is a decode of them. It
        was the other way once - `_read_from` called the archive's `read` and this
        arrived later, because a PNG decoded to text and re-encoded is a corrupt PNG.
        Then `read` turned out to be the *model's* read, numbering every line, so the
        text path moved onto this too.
        """
        async with self._archive(ctx, row) as archive:
            if archive is None:
                return None
            try:
                return await asyncio.to_thread(
                    archive.read_bytes, row.session_id or row.scope_key, path
                )
            except Exception as exc:
                # A 400 naming the reason rather than a 404: the file is listed, so
                # "missing" is the one thing this is not.
                raise BadRequestError(
                    message=_reason(exc), details={"workspace_id": str(row.id), "path": path}
                ) from exc

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
            async with self._archive(ctx, row) as archive:
                if archive is None:
                    return WorkspaceContents(entries=[])
                # `to_thread`, because `WorkspaceArchive` is a synchronous
                # `httpx.Client` and this is a round trip to the host. `flat_files`
                # runs it for up to 25 workspaces in one request, so the loop was
                # held for all 25 - and not only for that request.
                entries = await asyncio.to_thread(archive.ls, row.session_id or row.scope_key)
                return WorkspaceContents(entries=list(entries))
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
        """One file out of one workspace, as its own text.

        Shared by the two ways a workspace is addressed - through its conversation
        and by its own id - so a path that is refused one way cannot be readable
        the other.

        **`read_bytes` and a decode, never the backend's `read`.** That read is the
        model's: its docstring says "read a slice of a file with line numbers", and
        it returns every line behind a six-column gutter and a tab, capped at two
        thousand with `... (N more lines)` after them. It exists so an agent can
        cite a line it wants to edit, and it is not the file.

        Handed to a person it was three bugs at once: Source could not be copied
        because every line carried a number, an HTML preview rendered those numbers
        as page content - the iframe is given this text verbatim - and a file past
        two thousand lines was silently truncated with no `truncated` flag on the
        response to say so.
        """
        raw = (
            self._state_bytes(row, path)
            if row.backend == "state"
            else await self._read_bytes_from(ctx, row, path)
        )
        if raw is None:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            # The route serving this is the text one, so a caller has already
            # decided the file reads as characters - by suffix, which is a guess.
            # Saying so beats returning replacement characters that look like a
            # corrupted file.
            raise BadRequestError(
                message="This file is not text",
                details={"workspace_id": str(row.id), "path": path},
            ) from exc

    @staticmethod
    def _state_bytes(row: AgentWorkspace, path: str) -> bytes | None:
        """One file's bytes out of a state-backed workspace, or None when absent."""
        from pydantic_ai_backends import StateBackend

        backend = StateBackend(files=dict(row.files or {}))
        if not backend.exists(path):
            return None
        return backend.read_bytes(path)

    @asynccontextmanager
    async def _archive(self, ctx: AuthContext, row: AgentWorkspace) -> AsyncIterator[Any | None]:
        """A reader for the host volume behind a container-backed workspace.

        `None` when the workspace has no connection left to ask - the host was
        forgotten, or this is a Daytona sandbox, which keeps no host volume of
        ours to read. Either way the answer is "no files here", which is true, and
        distinct from the service being misconfigured: that raises.

        A context manager because `WorkspaceArchive` builds and *owns* an
        `httpx.Client` when it is not handed one, and exposes `close()` to release
        it. This used to return the archive and nothing ever closed it, so every
        listing and every read abandoned a connection pool for the garbage
        collector to notice later - and `flat_files` walks up to 25 workspaces in
        one request.
        """
        if row.connection_id is None:
            yield None
            return
        from pydantic_ai_backends.remote import WorkspaceArchive

        resolved = await self._connection(ctx, row.connection_id)
        if resolved.kind != "docker" or not resolved.row.base_url:
            yield None
            return
        archive = WorkspaceArchive(resolved.row.base_url, token=resolved.token)
        try:
            yield archive
        finally:
            # Closing a pool shuts sockets rather than waiting on the network, but it
            # is still the sync client's own call and there is no reason for the loop
            # to make it.
            await asyncio.to_thread(archive.close)

    async def _connection(self, ctx: AuthContext, connection_id: UUID) -> ResolvedConnection:
        """A connection, resolved at most once per service instance.

        `resolve` is a query plus a vault unwrap, and `flat_files` asked it per
        row - so a reader with twenty workspaces on one host paid twenty of both
        to read one page. The service is constructed per request by the DI
        container, so the cache lives exactly as long as the work that needs it.

        It holds an unsealed token for that lifetime, which is not a widening: the
        caller is already holding one to talk to the host, and it never leaves this
        process. Keyed on the id rather than the row, so two workspaces on one
        connection share the answer and two connections do not.
        """
        cached = self._connections_by_id.get(connection_id)
        if cached is None:
            cached = await self.connections.resolve(ctx, connection_id)
            self._connections_by_id[connection_id] = cached
        return cached


def _absent(row: AgentWorkspace, contents: WorkspaceContents, path: str) -> bool:
    """Whether a listing that could be read says this path is not in it.

    Only asked of a workspace kept on a host. A stored one has an authoritative
    oracle - `StateBackend.exists` - and using a *listing* as one there is wrong:
    `glob_info` does not match dotfiles, so `/.env` exists, reads fine, and is not
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


def stored_entries(files: dict[str, FileData]) -> list[FileInfo]:
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


PREVIEW_CHARS = 200
"""Enough of a stored text file for its tile to say what it is, and no more:
the tile is a hint, and the viewer is one click away for the rest."""


def stored_preview(data: FileData | None) -> str | None:
    """The first lines of a stored text file, or `None` where there is nothing a
    tile could honestly show.

    Reads the `FileData` shape `StateBackend` persists: text is lines under
    `content`, and anything that is not text carries `encoding` - whose base64
    would preview as noise, so it previews as nothing instead.
    """
    if data is None or data.get("encoding") is not None:
        return None
    lines = data.get("content") or []
    text = "\n".join(str(line) for line in lines[:8])
    return text[:PREVIEW_CHARS] or None


THUMBNAIL_BOX = (160, 128)
"""Twice the card's 64px band, so the tile is not soft on a retina screen."""

THUMBNAIL_SOURCE_LIMIT = 4 * 1024 * 1024
"""The largest stored image this will decode.

A listing reads up to 25 workspaces, so the work here is per file and has to stay
small. Above this the tile keeps its mark: a photograph nobody has resized is the
one case where decoding costs more than the hint is worth."""

THUMBNAIL_PIXEL_LIMIT = 16 * 1024 * 1024
"""The largest stored image this will decode, counted in pixels rather than bytes.

`THUMBNAIL_SOURCE_LIMIT` bounds what arrives, and compressed bytes are no bound on
what a decode costs: a 30 KB PNG may declare 8000x8000 and allocate a quarter of a
gigabyte the moment a pixel is asked for, on a request a person made by opening a
page. Pillow's own ceiling does not cover this - it refuses at 89 megapixels, which
catches the absurd and lets the merely expensive through, twenty times over. The
header is read before any pixel is, so the size it declares is checked here while
the decode is still hypothetical. A 12 MP photograph passes; that PNG does not."""

THUMBNAIL_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
"""What is offered a thumbnail, and it is the raster half of `INLINE_TYPES`.

`.svg` is absent for the reason it is absent there: it is a document with script in
it rather than a picture, and Pillow does not read one anyway. Suffix rather than
sniffing, so nothing outside this set is ever handed to a decoder."""


def stored_thumbnail(path: str, data: FileData | None) -> str | None:
    """A stored image scaled to a data URI, or `None` where a tile has nothing to draw.

    The counterpart of :func:`stored_preview` for the kind of file that has no first
    lines. Before this, an image in the All files grid was listed under the same grey
    glyph as a `.parquet` (#827).

    A data URI rather than an address, because the bytes are already in hand: they
    are base64 in the same JSONB document this listing reads for the preview, so
    scaling them here costs no request. The alternative - a URL per tile - is a
    request per tile in a grid of thirty, which is what `FileCard` was written not to
    do. It is scaled rather than sent whole for the same reason: a chart an agent drew
    is tens of kilobytes and would be sent in full to fill 64 pixels.

    What is drawn is what the file looks like, which takes two steps a scale alone
    does not: a camera's orientation lives in EXIF rather than in the pixels, so it is
    applied before the scale or the photograph is sideways on the tile; and an alpha
    channel is kept, because flattening a logo or a chart to RGB paints whatever was
    hidden under the transparency - usually black - across the card.

    Failure is a mark, not an error. A file whose suffix says PNG and whose bytes are
    not one is an agent's mistake at write time, and it must not take out the listing
    of every other file beside it - so the decoder's complaint is logged and the tile
    falls back to its glyph.

    Args:
        path: The file's path inside the workspace, whose suffix decides eligibility.
        data: The `FileData` the state backend stored, or `None` for a host-backed
            file this listing never fetched.
    """
    if data is None or data.get("encoding") != "base64":
        return None
    if PurePosixPath(path).suffix.lower() not in THUMBNAIL_SUFFIXES:
        return None
    content = data.get("content") or []
    try:
        raw = base64.b64decode("".join(str(line) for line in content), validate=True)
    except (BinasciiError, ValueError):
        logger.warning("workspace_thumbnail_undecodable", extra={"path": path})
        return None
    if len(raw) > THUMBNAIL_SOURCE_LIMIT:
        return None
    try:
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            if width * height > THUMBNAIL_PIXEL_LIMIT:
                return None
            ImageOps.exif_transpose(image, in_place=True)
            image.thumbnail(THUMBNAIL_BOX)
            scaled = BytesIO()
            mode = "RGBA" if image.has_transparency_data else "RGB"
            image.convert(mode).save(scaled, format="WEBP", quality=70)
    except Exception as exc:
        logger.warning(
            "workspace_thumbnail_failed",
            extra={"path": path, "error": exc.__class__.__name__},
        )
        return None
    return f"data:image/webp;base64,{base64.b64encode(scaled.getvalue()).decode()}"


def _reason(exc: Exception) -> str:
    """Why a host's files could not be read, in a sentence a client can show.

    The service's own detail is kept rather than replaced: for the commonest cause
    it names the exact setting (`workspace_root`), which is the difference between
    an operator fixing this in one line and filing a bug against us.
    """
    detail = str(exc).strip() or exc.__class__.__name__
    return f"This host's files could not be read. {detail}"


def stored_ceiling(row: AgentWorkspace) -> int | None:
    """What this workspace fills up against, or `None` when this platform is not the
    one holding the ceiling.

    A stored workspace is bytes in a JSONB column against a deployment-wide cap, and
    running out of it *refuses writes* - which the agent reports as a tool error in the
    middle of doing something, so a client that can show the fill approaching is worth
    the field. A container's ceiling belongs to its host and is only knowable by
    sampling the session, which is a round trip and therefore not something a listing
    answers; reporting the stored cap for one would name a limit that does not apply.

    Here rather than at each caller because two of them read it - the per-turn usage
    report and the workspace listings - and a second copy of "how full is it" drifts.
    """
    return settings.SANDBOX_STATE_MAX_BYTES if row.backend == "state" else None


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
