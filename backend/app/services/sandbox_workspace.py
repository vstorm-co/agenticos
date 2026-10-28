"""Opening the workspace a run works in, and putting it away afterwards.

The capability cannot do this. Opening a workspace reads and writes the database
— loading a stored document, recording which session belongs to which
conversation — and a capability is built inside `build_agent`, which holds no
session and must not acquire one. So the runner opens one here, passes the
workspace to the run - where every tool reaches it as `ctx.workspace` - and closes
it in the `finally` that already records what the run cost.

What "closing" means differs by backend, and the difference is the reason this
module exists rather than a helper on the capability:

* `state` lives in this database. Closing flushes the document, and nothing
  survives that is not flushed.
* `docker` lives in `sandboxd`, which owns its own lifecycle — idle reaping,
  ceilings, hibernation. Closing releases a *run-scoped* session as a courtesy.
  For a longer scope it records which session the row now holds, or forgets one
  found gone, and removes this run's spills, but leaves the session itself to
  `sandboxd`: correctness must not depend on this process getting to its
  `finally`.
* `daytona` is a cloud resource on the organization's own account, and the same
  applies with somebody else's invoice attached.
"""

import asyncio
import base64
import contextlib
import contextvars
import logging
from binascii import Error as BinasciiError
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageOps
from pydantic_ai.workspaces import Workspace, WorkspaceRef
from pydantic_ai_backends import FileData, FileInfo, StateBackend
from pydantic_ai_backends.remote.archive import DEFAULT_TIMEOUT_SECONDS
from pydantic_ai_backends.remote.wire import MAX_TREES
from pydantic_ai_backends.workspaces import (
    DaytonaWorkspace,
    SandboxdWorkspace,
    StateWorkspaceBackend,
)
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
from app.agents.capabilities.sandbox._recording import RecordingWorkspace
from app.agents.capabilities.tool_output_limits import OVERFLOW_PREFIX
from app.agents.spec import AgentSpec
from app.core.background import spawn_after_commit
from app.core.blocking import run_blocking
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
    WorkspaceCapacityError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_workspace import AgentWorkspace
from app.db.models.project import Project
from app.db.session import get_db_context, get_worker_db_context
from app.repositories import agent as agent_repo
from app.repositories import agent_workspace as workspace_repo
from app.repositories import conversation as conversation_repo
from app.repositories import member as member_repo
from app.repositories import pending_sandbox_destroy as pending_destroy_repo
from app.repositories import project_repo
from app.services.access import PROJECT, accessible_ids, resolve_access
from app.services.sandbox_connection import ResolvedConnection, SandboxConnectionService
from app.services.sandbox_runtimes import runtime_briefing, runtime_parses_documents
from app.services.sandboxd_compat import explain_unavailable
from app.services.skill_workspace import LEGACY_SKILLS_ROOT, RESERVED_SKILL_PREFIXES

logger = logging.getLogger(__name__)

SANDBOX_CAPABILITY_ID = "sandbox"

STATE_PROVIDER = "state"
"""`WorkspaceRef.provider` of a stored document, as `StateWorkspace` names it."""

_MAX_LISTED_DEPTH = 6
"""How many levels of a workspace a listing shows, the root being the first."""

_MAX_LISTED_ENTRIES = 2000
"""Where a listing stops. A host holding a `node_modules` must not turn one
workspace into ten thousand rows on a page about twenty-five of them."""

_HOST_CALLS_AT_ONCE = 8
"""How many calls to sandbox hosts the whole process has in flight - one `ls` of
a walk or one `read_bytes` each count as one. The listings that read more than one
workspace used to read them one after another, so the page waited for the sum of
twenty-five walks; with this it waits for the slowest few."""

_HOST_CALLS = ThreadPoolExecutor(
    max_workers=_HOST_CALLS_AT_ONCE, thread_name_prefix="workspace-host"
)
"""The threads host calls run on, and the bound on them.

Not the loop's default executor, which `to_thread` uses: that one also carries
`bcrypt` and pinned-host DNS, and it has `min(32, cpus + 4)` threads - six on a
two-core host. A host that stops answering holds a thread for the browse timeout,
or sixty seconds for a read, so a few people opening the Workspaces page at once
would leave sign-in queueing behind them. A per-request limit does not prevent
that, since every request brings its own; a pool of the process's own does, and
a dead host then slows only other host calls.

Unlike `app.core.blocking`, which carries file work, there is no admission gate:
what waits in this queue is a bound method and two strings rather than an upload
buffer, and a cancelled caller's call that has not started is dropped from it.
Threads start on first use and are joined at interpreter exit."""


async def _on_host_thread[T](call: Callable[..., T], *args: object) -> T:
    """Run a blocking host call on `_HOST_CALLS`, carrying the caller's context as
    `to_thread` would, so its spans stay under the request's trace."""
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        _HOST_CALLS, partial(context.run, call, *args)
    )


_sandboxd_client: httpx.AsyncClient | None = None
_sandboxd_loop: asyncio.AbstractEventLoop | None = None


def _sandboxd_http() -> httpx.AsyncClient:
    """The client every `sandboxd` workspace in this process shares.

    Without one, `SandboxdWorkspace` builds a client per request: a new
    connection, and an SSL context, for every command and every file operation
    of a run - several milliseconds each, against operations that take four
    since the service answers file calls itself.

    Rebuilt when the event loop changes, as `model_catalog`'s client is: its
    connections belong to the loop that opened them, and one process runs
    requests, tests and jobs on different loops. Unbounded, because a
    command holds its connection for as long as it runs, and a pool cap would
    queue the next run's commands behind the last one's. The timeouts ride each
    request.
    """
    global _sandboxd_client, _sandboxd_loop
    loop = asyncio.get_running_loop()
    if _sandboxd_client is None or _sandboxd_client.is_closed or _sandboxd_loop is not loop:
        _sandboxd_client = httpx.AsyncClient(limits=httpx.Limits(max_connections=None))
        _sandboxd_loop = loop
    return _sandboxd_client


async def close_sandboxd_client() -> None:
    """Close the shared `sandboxd` client at shutdown.

    A client whose loop has already gone has nothing left to release, and
    `aclose` says so by raising; dropping the reference is the close then.
    """
    global _sandboxd_client, _sandboxd_loop
    if _sandboxd_client is not None and not _sandboxd_client.is_closed:
        try:
            await _sandboxd_client.aclose()
        except RuntimeError:
            logger.debug("sandboxd client outlived its event loop; dropping it unclosed")
    _sandboxd_client = None
    _sandboxd_loop = None


_BROWSE_TIMEOUT_SECONDS = 10.0
"""How long a listing waits on a host. The archive's own default is sixty seconds,
and a host that has gone away held the whole Workspaces page for that long before
it could say "this host did not answer". A download keeps the default."""


async def _concurrently[T](calls: Sequence[Callable[[], Coroutine[object, object, T]]]) -> list[T]:
    """Every call's result in the order given, run side by side.

    A `TaskGroup` rather than `gather`: a call that raises cancels the others and
    the group waits for them, so none keeps running after the request has failed
    and reaches its database session afterwards. How many reach a host at once is
    `_HOST_CALLS`'s to bound, not this.
    """
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(call()) for call in calls]
    return [task.result() for task in tasks]


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

    truncated: bool = False
    """Whether the walk stopped before the workspace did.

    A separate answer from `unreadable_reason`: the host answered, and this is
    still not all of it. A listing bounded at 2,000 entries and six levels is a
    listing a person reads as the whole of what an agent is keeping, which for a
    workspace holding a checkout or a `node_modules` it is not.
    """

    previews: dict[str, str] = field(default_factory=dict)
    """The first lines of each stored text file, by path - what its tile peeks at."""

    thumbnails: dict[str, str] = field(default_factory=dict)
    """Each small image scaled to a `data:` URI, by path, within the fetch budget."""


@dataclass(frozen=True)
class WorkspaceOverview:
    """One workspace as a table shows it: the row, plus what makes it readable."""

    row: AgentWorkspace
    agent_name: str
    agent_slug: str
    """The handle, which is what the generated face is drawn from - so a row
    here draws the same picture the agent's own page does."""
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
    owner_name: str | None = None
    """Whose files these are, named - or `None` where nobody owns them.

    `owner_ref` is the raw string the scope key was built from, and it is only
    set for a `user`-scoped workspace: a UUID for an account, or a platform id
    for one whose owner arrived through Slack and has no account here (#131). So
    an account is resolved to its email and a platform id is passed through
    verbatim, which is what the table renders as an unlinked label.

    Not `owner_label`, which reads like an identity and is not one: it answers
    with the *scope* - "This conversation", "Shared by everyone who uses this
    agent" - so a column drawing it under an Owner heading names nobody (#137).
    """


PLATFORM_DIR = ".agenticos"
"""Where the platform keeps its own working files in a workspace - a coding task's
events and session (`app.agents.capabilities.coding_agent._task.WORK_DIR`), a
project's task files - and so not somewhere a person writes or browses."""

NOT_BROWSABLE = (
    *RESERVED_SKILL_PREFIXES,
    f"{OVERFLOW_PREFIX}/",
    f"{PLATFORM_DIR}/",
    f"workspace/{PLATFORM_DIR}/",
)
"""Prefixes the file browser drops, matched after the leading slash.

All are the platform's own writing rather than the agent's work for a person, and
all are needed on disk: a skill's resource is a script the shell runs and
`collect_changes` diffs, a spill is what a tool's overflowing output was written
to, and `.agenticos/` holds a coding task's events and the session the next task
continues. A listing of what an agent is keeping is not the place any of them
belongs - `/workspaces` was mostly `skills/<name>/SKILL.md` before this (#1064),
and `.agenticos/coding-agent/<id>.exit` once the coding agent ran."""


TOOLING_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".git",
        ".next",
        ".cache",
    }
)
"""Folders a program's tools fill, dropped wherever they sit in a workspace.

A coding agent that sets up a project installs its dependencies and runs its
tests in the sandbox, and one FastAPI app with a virtualenv is a thousand files -
`site-packages`, caches, compiled bytecode - which buried the dozen it wrote
among them on Documents. They stay on disk for the next task; they are not what a
person comes to the page for."""


def browsable(entries: list[FileInfo]) -> list[FileInfo]:
    """The entries a person is shown, without what the platform or a toolchain put there.

    The directories too, not only what is in them: a container lists `skills`
    itself beside its files, and with the files dropped it read as an empty
    folder the agent had made for nothing.
    """

    def hidden(path: str) -> bool:
        relative = path.lstrip("/").rstrip("/")
        if f"{relative}/".startswith(NOT_BROWSABLE):
            return True
        return any(segment in TOOLING_DIRS for segment in relative.split("/"))

    return [entry for entry in entries if not hidden(str(entry.get("path", "")))]


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


SandboxWaitSink = Callable[[bool], Awaitable[None]]
"""Told `True` when a run's sandbox is still being opened - usually its image
being built - and `False` once that open is over, opened or failed.

Handed in when the workspace is opened, not attached afterwards: the run's
preparation already opens the session - it snapshots the workspace before the
first model request - and that open is where an image build waits (#2222)."""


@dataclass
class _OpeningNotice:
    """Turns the client's one "still opening" into a start and an end.

    `SandboxdWorkspace` says only that opening is taking a while. The end is the
    first operation to finish after that, since the session opens inside it -
    and an end tied to a tool result instead let an unrelated, faster tool clear
    the notice while the image was still building.
    """

    sink: SandboxWaitSink
    announced: bool = False

    async def waiting(self) -> None:
        self.announced = True
        await self.sink(True)

    async def settled(self) -> None:
        if self.announced:
            self.announced = False
            await self.sink(False)


@dataclass(frozen=True)
class WorkspaceFlushFailure:
    """A visible failure to persist the run's workspace, with recovery when possible."""

    error: WorkspaceCapacityError | ExternalServiceError


@dataclass
class OpenWorkspace:
    """A workspace a run is using, and what it takes to put it away."""

    workspace: Workspace
    """What the run works in. The runner passes it to the run as `workspace=`,
    which is what every tool reaches as `ctx.workspace`, and stages skills and
    attachments into it beforehand."""

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

    parses_documents: bool = False
    """Whether the container can read a PDF, a `.docx` or a spreadsheet itself.

    Not `briefing is not None`, which is what it was and what made an inaccurate
    package hint into missing data: a briefing falls back to the catalogue's first
    entry for a run that named no runtime, and the host is the one that actually
    chooses in that case. `runtime_parses_documents` answers only for an alias that
    was named, shipped here, and installs the parser - so a custom host gets the
    extracted text written beside the original, as it did before any of this.
    """

    opened_version: int | None = None
    """What `version` said when this run loaded the document.

    Carried so the flush can tell whether somebody else stored one in between.
    `None` where there is no row to compare against - a run-scoped workspace, or a
    container-backed one, which keeps its files on the host rather than here.
    """

    opened_files: dict[str, Any] = field(default_factory=dict)
    opened_directories: tuple[str, ...] = ()
    """The document as this run loaded it, which is what tells the flush what the
    run changed from what somebody else stored in between. A shallow copy: the
    file entries themselves are shared with the document, never mutated in place.
    """

    document: CappedStateBackend | None = None
    """The stored document a `state` workspace works in, flushed back at close."""

    sandbox: SandboxdWorkspace | DaytonaWorkspace | None = None
    """What supplies a container-backed workspace, for removing a `run`-scoped one."""

    spills: list[str] = field(default_factory=list)
    """Every spill handle `tool_output_limits` wrote to this workspace this run.

    Registered beside the backend under `SPILL_LOG_RESOURCE`, appended by the
    overflow store, and read back by `close`: a container-backed workspace whose
    scope outlives the run deletes exactly these paths, so a spill never survives
    the run that produced it (#803). Exact handles rather than the `tool_output/`
    prefix, because concurrent runs share a longer-scoped workspace and a prefix
    sweep would take another run's spills mid-flight.
    """


def project_sandbox(project: Project) -> SandboxConfig:
    """The workspace every run in a project shares, as a sandbox configuration.

    The shell is always on: a project is somewhere work is done, and which agent
    answered a chat in it should not decide whether its files can be run.
    """
    return SandboxConfig(
        backend=cast("Literal['state', 'service']", project.backend),
        connection_id=project.sandbox_connection_id,
        runtime=project.runtime,
    )


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


def _provider(sandbox: SandboxdWorkspace | DaytonaWorkspace) -> str:
    """The provider name the refs of `sandbox`'s workspaces carry."""
    return sandbox.provider if isinstance(sandbox, SandboxdWorkspace) else "daytona"


def _is_spill(path: str) -> bool:
    """Whether a path in the stored document is a `tool_output_limits` spill (#803).

    A spilled tool return goes to the run's workspace under the reserved
    `tool_output/` prefix so `read_tool_result` can page through it, but it is a
    within-run artefact and must never survive into the persisted document. On a
    longer-scoped state workspace it otherwise accumulates every run and counts
    against `SANDBOX_STATE_MAX_BYTES`, until the cap starts refusing the agent's
    own writes. Stripping it at flush keeps the invariant "the stored document
    holds the agent's files, never its spills", every run self-healing whatever a
    prior one left. Document keys are normalized with a leading slash; the
    `lstrip` tolerates both forms.
    """
    relative = path.lstrip("/")
    return relative == OVERFLOW_PREFIX or relative.startswith(f"{OVERFLOW_PREFIX}/")


def _is_legacy_skill(path: str) -> bool:
    """Whether a path is in the skills tree that predates the move inside the workspace.

    A conversation-, user- or agent-scoped `state` workspace created before skills
    moved to `SKILLS_ROOT` still holds them under `LEGACY_SKILLS_ROOT`, and nothing
    writes there any more. Left in place, the next run materialises a second
    complete copy beside the first, both are persisted, and both are charged
    against `SANDBOX_STATE_MAX_BYTES` - so an upgrade roughly doubles the skill
    footprint and can start refusing the agent's own writes near the cap.

    Dropped at flush, where spills are dropped and for the same reason: it is the
    platform's own writing, not the turn's work, and the agent is told where the
    files are now. The current root survives this because it strips to
    `workspace/skills/...`, which is not under the legacy prefix.
    """
    legacy = LEGACY_SKILLS_ROOT.strip("/")
    relative = path.lstrip("/")
    return relative == legacy or relative.startswith(f"{legacy}/")


def _same_contents(files: dict[str, FileData], opened: dict[str, Any]) -> bool:
    """Whether a run left every file as it found it, timestamps aside.

    Every run writes its skills into the workspace again, so a file can be new
    and still say exactly what it said: only its `modified_at` moved. That is
    not a change worth storing the whole document for.
    """
    if files.keys() != opened.keys():
        return False
    for path, data in files.items():
        before = opened[path]
        if data is before:
            continue
        if data.get("content") != before.get("content") or data.get("encoding") != before.get(
            "encoding"
        ):
            return False
    return True


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
        # The listings read hosts concurrently, and resolving a connection is a
        # query on the one session this service holds - which must not be used by
        # two coroutines at once.
        self._resolving = asyncio.Lock()
        # Archives kept open for the length of `_sharing_archives`, one per host:
        # `None` outside it, where each read builds and closes its own.
        self._shared_archives: dict[UUID, Any] | None = None

    async def open(
        self,
        spec: AgentSpec,
        *,
        ctx: AuthContext,
        identity: WorkspaceIdentity,
        scope_override: SessionScope | None = None,
        on_wait: SandboxWaitSink | None = None,
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
        if scope == "project":
            from app.services.project_workspace_guard import project_for_workspace

            project = await project_for_workspace(self.db, ctx, identity.project_id)
            config = project_sandbox(project)
            identity = replace(identity, project_workspace_id=project.workspace_generation)
        return await self._open_config(
            config,
            ctx=ctx,
            identity=identity,
            scope=scope,
            on_wait=on_wait,
        )

    async def _open_config(
        self,
        config: SandboxConfig,
        *,
        ctx: AuthContext,
        identity: WorkspaceIdentity,
        scope: SessionScope,
        on_wait: SandboxWaitSink | None = None,
    ) -> OpenWorkspace:
        """`open`, for a configuration already read out of a spec or a project."""
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
        return await self._open_service(config, identity, key, scope, resolved, on_wait=on_wait)

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
        row = await self._row(config, identity, key, scope)
        document = CappedStateBackend(
            dict(row.files or {}) if row is not None else {},
            row.directories or () if row is not None else (),
            max_bytes=settings.SANDBOX_STATE_MAX_BYTES,
        )
        # Served under the scope key, so a history that names it - the ref the
        # last run recorded - names this very document.
        backend = StateWorkspaceBackend(
            {key: document}, ref=WorkspaceRef(provider=STATE_PROVIDER, id=key)
        )
        return OpenWorkspace(
            workspace=Workspace(backend),
            document=document,
            kind="state",
            scope=scope,
            scope_key=key,
            row_id=row.id if row is not None else None,
            opened_version=row.version if row is not None else None,
            opened_files=dict(row.files or {}) if row is not None else {},
            opened_directories=tuple(row.directories or ()) if row is not None else (),
        )

    async def _open_service(
        self,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
        resolved: ResolvedConnection,
        *,
        on_wait: SandboxWaitSink | None = None,
    ) -> OpenWorkspace:
        """A workspace on one of the organization's registered connections.

        Nothing starts here. The workspace opens its session on the first
        operation - under the scope key, attaching when it exists - so an agent
        granted a workspace it never touches costs no container and not even a
        round trip.

        **Once a session was opened, a later run only attaches.** The row records
        the session at close (`_settle_session`), and from then on the workspace
        is opened by that ref, which the provider answers with the session or with
        `WorkspaceUnavailableError` - never with a new, empty one under the same
        name. A conversation whose files were purged on the host is told so,
        rather than carrying on in an empty directory as if nothing happened.

        The connection arrives resolved rather than being read from settings,
        which is what makes two hosts possible and what keeps the credential in
        the vault. It is resolved by the caller because the key depends on it -
        resolving can fail for reasons that were fine at publish time (a key
        rotated away, a host switched off) and each of those says which.
        """
        briefing: str | None = None
        parses_documents = False
        notice = _OpeningNotice(on_wait) if on_wait is not None else None
        sandbox = self._service_capability(
            resolved,
            key,
            runtime=config.runtime,
            tenant=str(identity.organization_id),
            on_wait=notice.waiting if notice is not None else None,
        )
        if resolved.kind != "daytona":
            alias = config.runtime or resolved.row.default_runtime or None
            briefing = runtime_briefing(alias)
            parses_documents = runtime_parses_documents(alias)

        row = await self._row(config, identity, key, scope, connection_id=resolved.row.id)
        opened = (
            None
            if row is None or row.session_id is None
            else WorkspaceRef(provider=_provider(sandbox), id=row.session_id)
        )
        # Wrapped so what the agent does in this sandbox is recorded on our side.
        # The service keeps its own log and it is 200 entries in that process's
        # memory, gone on restart, so a sandbox that outlives the service's uptime
        # had no audit at all (#1061). Wrapping here rather than calling from each
        # tool is what makes it impossible to forget for the ninth tool.
        recorder = RecordingWorkspace(
            Workspace(sandbox.backend(opened)),
            db=self.db,
            organization_id=identity.organization_id,
            session_key=key,
            agent_id=identity.agent_id,
            run_id=identity.run_id,
            on_settled=notice.settled if notice is not None else None,
            explain_unavailable=(
                partial(explain_unavailable, base_url=sandbox.service_url, client=_sandboxd_http())
                if isinstance(sandbox, SandboxdWorkspace)
                else None
            ),
        )
        return OpenWorkspace(
            workspace=recorder,
            sandbox=sandbox,
            kind="service",
            scope=scope,
            scope_key=key,
            row_id=row.id if row is not None else None,
            connection_id=resolved.row.id,
            briefing=briefing,
            parses_documents=parses_documents,
        )

    @staticmethod
    def _service_capability(
        resolved: ResolvedConnection,
        key: str,
        *,
        runtime: str | None = None,
        tenant: str | None = None,
        on_wait: Callable[[], Awaitable[None]] | None = None,
    ) -> SandboxdWorkspace | DaytonaWorkspace:
        """What supplies the sandbox named `key` on one of the organization's connections.

        Named by the key rather than by the provider: the key is where "who shares
        files with whom" became mechanical (`scope_key`), so every run of a scope
        opens the same session - and the first of two concurrent ones creates it
        while the other attaches - without this database recording a provider's
        id first.
        """
        if resolved.kind == "daytona":
            from daytona import DaytonaConfig

            # The organization's own key, from the connection, from the vault. Never
            # the SDK's `DAYTONA_API_KEY` fallback, which would put every tenant's
            # sandboxes on whichever account the deployment happens to have set.
            return DaytonaWorkspace(config=DaytonaConfig(api_key=resolved.token), sandbox_name=key)
        if not resolved.row.base_url:
            # Without an address the client would post the organization's token
            # at whatever a relative URL resolves to.
            raise BadRequestError(
                message="This sandbox connection has no address.",
                details={"connection_id": str(resolved.row.id)},
            )
        return SandboxdWorkspace(
            service_url=resolved.row.base_url,
            token=resolved.token,
            # One provider name per connection, so a ref from one host is never
            # read as a session on another.
            provider=f"sandboxd:{resolved.row.id}",
            # The spec's alias wins, then the connection's default, then whatever
            # the service itself defaults to. Three levels because each answers a
            # different question: what this agent needs, what this host prefers,
            # and what exists at all.
            runtime=runtime or resolved.row.default_runtime,
            # The organization, as a capacity label the service counts against
            # its per-tenant ceiling. It grants nothing - only the service token
            # opens a session at all - and it is what stops one talkative
            # organization occupying the pool of the whole installation.
            tenant=tenant,
            session_name=key,
            # Opening can build the runtime's image first; this is how the chat
            # learns to say so instead of sitting silent (#2222).
            on_wait=on_wait,
            client=_sandboxd_http(),
        )

    async def _row(
        self,
        config: SandboxConfig,
        identity: WorkspaceIdentity,
        key: str,
        scope: SessionScope,
        *,
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
            # A project's container is every agent's in it and no one agent's.
            agent_id=None if scope == "project" else identity.agent_id,
            project_id=identity.project_id if scope == "project" else None,
            conversation_id=(identity.conversation_id if scope == "conversation" else None),
            owner_ref=identity.user_id if scope == "user" else None,
            scope=scope,
            scope_key=key,
            backend=config.backend,
            connection_id=connection_id,
        )

    async def open_project(self, ctx: AuthContext, project: Project) -> OpenWorkspace:
        """A project's container, opened outside any run - to add or remove files.

        The caller has already decided the caller may work in the project. The
        same key a run in the project opens, so a file put here is the file the
        agent finds, and `close` must follow as it does after a run.
        """
        return await self._open_config(
            project_sandbox(project),
            ctx=ctx,
            identity=WorkspaceIdentity(
                organization_id=ctx.organization_id,
                agent_id=None,
                run_id=None,
                project_id=project.id,
                project_workspace_id=project.workspace_generation,
            ),
            scope="project",
        )

    async def project_files(
        self, ctx: AuthContext, project: Project
    ) -> tuple[AgentWorkspace, WorkspaceContents] | None:
        """What a project's container holds, read off the host without starting it.

        `None` before anything has been put in it. The caller has already decided
        the caller may see the project.
        """
        row = await workspace_repo.get_for_project(
            self.db, organization_id=ctx.organization_id, project_id=project.id
        )
        if row is None:
            return None
        return row, await self._tiled(ctx, row)

    async def project_bytes(self, ctx: AuthContext, project: Project, *, path: str) -> bytes:
        """One file of a project's container, as bytes.

        Raises:
            NotFoundError: If the project holds no files, or no such file.
            BadRequestError: If the host cannot be read.
        """
        row = await workspace_repo.get_for_project(
            self.db, organization_id=ctx.organization_id, project_id=project.id
        )
        if row is None:
            raise NotFoundError(
                message="This project holds no files", details={"project_id": str(project.id)}
            )
        return await self._bytes_from(ctx, row, await self._browsable(ctx, row), path)

    async def purge_project(self, ctx: AuthContext, project: Project) -> None:
        """Remove every container a project has had from its host, before the project goes.

        Every one, not the latest: a project moved to another sandbox connection
        left a container on the first, and the rows naming them go with the
        project - after which nothing would know to delete that one.
        """
        rows = await workspace_repo.list_for_project(
            self.db, organization_id=ctx.organization_id, project_id=project.id
        )
        for row in rows:
            if row.backend != "state":
                await self._purge_remote(ctx, row)

    async def close(
        self, workspace: OpenWorkspace | None, *, keep_spills: bool = False
    ) -> WorkspaceFlushFailure | None:
        """Persist or release what the run was using.

        Return a typed failure rather than raising past terminal accounting.
        Callers must report that failure after recording the run's cost or
        before acknowledging a project mutation. A rejected concurrent merge
        includes a separately committed recovery workspace in its error.

        Args:
            keep_spills: Leave this run's spilled tool returns where they are -
                for a run parked on an approval or a question, whose history
                still names them.
                Deleted at the park, the resumed run was handed handles to files
                that no longer existed, and a shell sent to read one found no
                directory. The run that resumes it spills into the same
                workspace, and the next close that is not a park strips a
                `state` workspace of all of them; on a container they stay until
                the session is reaped.
        """
        if workspace is None:
            return None
        try:
            if workspace.kind == "state":
                async with self.db.begin_nested():
                    return await self._flush_state(workspace, keep_spills=keep_spills)
            if workspace.scope == "run":
                await self._release(workspace)
            elif not await self._settle_session(workspace) and not keep_spills:
                await self._prune_spills(workspace)
        except Exception:
            logger.exception("workspace_close_failed", extra={"scope_key": workspace.scope_key})
            return WorkspaceFlushFailure(
                ExternalServiceError(
                    message="The workspace could not be saved. Check the run logs."
                )
            )
        return None

    async def _flush_state(
        self, workspace: OpenWorkspace, *, keep_spills: bool
    ) -> WorkspaceFlushFailure | None:
        document = workspace.document
        if document is None:  # pragma: no cover - `open` sets one on every `state` workspace
            raise RuntimeError("A state workspace was opened without its document")

        def dropped(path: str) -> bool:
            return _is_legacy_skill(path) or (not keep_spills and _is_spill(path))

        files = {path: data for path, data in document.files.items() if not dropped(path)}
        directories = sorted(path for path in document.directories if not dropped(path))
        if (
            workspace.row_id is not None
            and _same_contents(files, workspace.opened_files)
            and directories == sorted(workspace.opened_directories)
        ):
            # Most turns change nothing. Storing the document anyway rewrote the
            # whole column - and its WAL - on every message, at whatever size the
            # workspace had reached, and bumped the version so a concurrent run
            # merged against a change that was not there.
            await workspace_repo.mark_used(self.db, workspace_id=workspace.row_id)
            return None
        # `populate_existing`, so this is a read of what is *committed* rather than
        # of what this session loaded at `open`. Without it the identity map answers
        # with the row as it was, and a flush by another run - another person under
        # `agent` scope, the same person on a second surface - is invisible by
        # construction. Locked from this read to the commit: two flushes that both
        # read the same version before either wrote would each skip the merge,
        # and the later write would erase the earlier. Locked, the second waits,
        # reads the first's version and merges onto it.
        row = (
            None
            if workspace.row_id is None
            else await self.db.get(
                AgentWorkspace,
                workspace.row_id,
                populate_existing=True,
                with_for_update={"key_share": True},
            )
        )
        if row is None:
            # The conversation was deleted while the run was in flight. The files
            # belonged to it, so there is nothing to keep.
            return None
        own_files, own_directories = files, directories
        if workspace.opened_version is not None and row.version != workspace.opened_version:
            files, directories = self._merged(workspace, row, files, directories)
        size = document_size(files, directories)
        # A lowered setting must still allow an existing larger document to shrink.
        ceiling = max(
            settings.SANDBOX_STATE_MAX_BYTES,
            document_size(row.files or {}, row.directories or ()),
        )
        if size > ceiling:
            recovery_id = await self._recover_state(row, own_files, own_directories)
            return WorkspaceFlushFailure(
                WorkspaceCapacityError(
                    message=(
                        "Concurrent changes filled the shared workspace. This operation's files "
                        f"are preserved in Documents as recovery workspace {recovery_id}. "
                        "Free space before copying them back."
                    ),
                    details={"recovery_workspace_id": str(recovery_id)},
                )
            )
        await workspace_repo.save_files(
            self.db,
            workspace=row,
            files=files,
            directories=directories,
            bytes_total=size,
        )
        return None

    @staticmethod
    async def _recover_state(
        source: AgentWorkspace, files: dict[str, FileData], directories: list[str]
    ) -> UUID:
        """Commit the losing snapshot with the source's exact visibility and lifetime.

        Separate from the caller: an upload returning a conflict rolls its request
        back, and must not roll back the only recoverable copy with it. Recovery
        keys are never opened by runs. A source foreign key also removes the copy
        when source deletion was waiting for this merge's lock. Existing tenant
        and scope filters govern every read.
        """
        size = document_size(files, directories)
        if size > settings.SANDBOX_STATE_MAX_BYTES:
            raise RuntimeError("A recovery snapshot exceeds the workspace storage limit")
        async with get_worker_db_context() as db:
            recovery = await workspace_repo.create(
                db,
                organization_id=source.organization_id,
                agent_id=source.agent_id,
                project_id=source.project_id,
                conversation_id=source.conversation_id,
                owner_ref=source.owner_ref,
                scope=source.scope,
                scope_key=f"recovery-{uuid4().hex}",
                recovery_of_id=source.id,
                backend="state",
            )
            await workspace_repo.save_files(
                db,
                workspace=recovery,
                files=files,
                directories=directories,
                bytes_total=size,
            )
            recovery_id = recovery.id
        logger.warning(
            "workspace_capacity_conflict",
            extra={"workspace_id": str(source.id), "recovery_id": str(recovery_id)},
        )
        return recovery_id

    @staticmethod
    def _merged(
        workspace: OpenWorkspace,
        row: AgentWorkspace,
        files: dict[str, FileData],
        directories: list[str],
    ) -> tuple[dict[str, FileData], list[str]]:
        """This run's changes laid over what somebody else stored since it opened.

        Two runs holding one workspace - a project's teammates, every user of an
        `agent`-scoped one - each load the document and store it at the end, and
        storing it whole let the second erase whatever the first had written in
        between. So only what this run changed from the document it loaded is
        applied, path by path, over the stored one: a file it wrote or removed
        is its, and everything else stays as the other run left it.

        A path both runs changed takes this run's version, the later one, and is
        logged by name - "a file went missing" is the report that arrives, and
        only the path and the two versions make it actionable.
        """
        base, theirs = workspace.opened_files, dict(row.files or {})
        merged = dict(theirs)
        conflicts: list[str] = []
        for path in set(base) | set(files):
            mine = files.get(path)
            if mine == base.get(path):
                continue
            if theirs.get(path) != base.get(path) and theirs.get(path) != mine:
                conflicts.append(path)
            if mine is None:
                merged.pop(path, None)
            else:
                merged[path] = mine
        base_dirs, mine_dirs = set(workspace.opened_directories), set(directories)
        merged_dirs = (set(row.directories or ()) | (mine_dirs - base_dirs)) - (
            base_dirs - mine_dirs
        )
        if conflicts:
            logger.warning(
                "workspace_flush_conflict",
                extra={
                    "scope_key": workspace.scope_key,
                    "scope": workspace.scope,
                    "opened_version": workspace.opened_version,
                    "found_version": row.version,
                    "paths_overwritten": sorted(conflicts),
                },
            )
        return merged, sorted(merged_dirs)

    async def _settle_session(self, workspace: OpenWorkspace) -> bool:
        """Record which session this workspace is now, or forget a lost or mismatched one.

        A session the run opened is recorded on the row, so the next run attaches
        to it rather than opening one by name - which is what lets a purged one
        be noticed at all. A session the run found gone is forgotten, so the next
        run starts a fresh one: this run has already reported the loss, through
        the tool or the staging that hit it, and the turn after it should not hit
        it again.

        A session on a service of another version is forgotten the same way,
        though it is alive (see the branch below).

        Returns:
            Whether the session was lost or mismatched. Either way its spills are
            not pruned: a lost session has none left, and a mismatched one is on a
            service that cannot run the prune.
        """
        row = (
            None
            if workspace.row_id is None
            else await self.db.get(AgentWorkspace, workspace.row_id, populate_existing=True)
        )
        recorder = workspace.workspace
        lost = isinstance(recorder, RecordingWorkspace) and recorder.lost
        if row is None:
            return lost
        if lost:
            logger.warning(
                "workspace_session_lost",
                extra={"scope_key": workspace.scope_key, "session_id": row.session_id},
            )
            if isinstance(workspace.sandbox, DaytonaWorkspace):
                await self._discard_lost_sandbox(
                    workspace.sandbox, row.session_id or workspace.scope_key
                )
            await workspace_repo.record_session(self.db, workspace=row, session_id=None)
            return True
        if isinstance(recorder, RecordingWorkspace) and recorder.mismatched:
            # Alive, but on a service of another version (#2484). Its ref is
            # forgotten so the next run opens the scope by name: an older service
            # ignores attach-by-ref and refuses a live session with a 409.
            logger.warning(
                "workspace_session_version_mismatch",
                extra={"scope_key": workspace.scope_key, "session_id": row.session_id},
            )
            await workspace_repo.record_session(self.db, workspace=row, session_id=None)
            return True
        ref = workspace.workspace.ref
        if ref is not None and ref.id != row.session_id:
            await workspace_repo.record_session(self.db, workspace=row, session_id=ref.id)
        return False

    async def _discard_lost_sandbox(self, sandbox: DaytonaWorkspace, name: str) -> None:
        """Delete a Daytona sandbox found gone, so the next run can open its name afresh.

        A purged container is gone from its host. A Daytona sandbox in `error` or
        `build_failed` is not: it still holds the scope's name, the next run opening
        by that name would attach to it and be refused again, turn after turn, and
        nothing else deletes it. Best effort, because the loss is already reported.
        """
        try:
            await sandbox.destroy(WorkspaceRef(provider=_provider(sandbox), id=name))
        except Exception:
            logger.warning(
                "workspace_lost_sandbox_not_deleted", extra={"sandbox": name}, exc_info=True
            )

    async def _prune_spills(self, workspace: OpenWorkspace) -> None:
        """Delete this run's spilled tool returns off a workspace that outlives it.

        The container-backed half of #803: a `state` workspace has its spills
        stripped at flush and a `run`-scoped container dies purged, but a
        `conversation`/`user`/`agent`-scoped container keeps its filesystem across
        runs, so the spills this run wrote are removed here, by the exact handles
        the overflow store recorded. Another run's spills are untouched - its
        handles are in its own workspace's list.

        Two commands rather than a removal per handle, so a hundred spills are two
        round trips, and argv rather than a shell line, so no path is ever parsed
        as one. The `rmdir` afterwards clears the now-empty run directories; it
        fails where a concurrent run still keeps files, which is the correct
        answer - so only a refused `rm` is the failure the warning below exists
        for. Best-effort like `_release`: a run that crashes before its `finally`
        leaves its spills for the next manual sweep, and `close` already logs
        whatever raises here.
        """
        handles = [handle for handle in workspace.spills if _under_overflow(handle)]
        if not handles:
            return
        directories = sorted(
            {parent for handle in handles for parent in _overflow_parents(handle)},
            key=lambda directory: directory.count("/"),
            reverse=True,
        )
        result = await workspace.workspace.run(["rm", "-f", "--", *handles])
        await workspace.workspace.run(["rmdir", "--", *directories])
        if result.exit_code != 0:
            logger.warning(
                "workspace_spill_prune_failed",
                extra={
                    "scope_key": workspace.scope_key,
                    "handles": len(handles),
                    "output": result.stderr,
                },
            )

    async def _release(self, workspace: OpenWorkspace) -> None:
        """Remove a run-scoped sandbox, as a courtesy rather than a guarantee.

        `sandboxd` reaps idle sessions on its own, which is what makes this safe
        to be best-effort for a container: a run that crashes between opening a
        sandbox and getting here leaves one behind for the idle timeout and no
        longer.

        A Daytona sandbox has no such net. It is a cloud resource on the
        organization's own account, so the courtesy is the only thing that ends
        it, which is why the call has to actually land.
        """
        ref = workspace.workspace.ref
        if workspace.sandbox is None or ref is None:
            return  # never opened: nothing to remove
        await workspace.sandbox.destroy(ref)

    async def retire_project_source(
        self, ctx: AuthContext, *, source_id: UUID, project_id: UUID
    ) -> None:
        """Retire the verified source in the same transaction as target activation."""
        source = await workspace_repo.get(self.db, source_id, organization_id=ctx.organization_id)
        if source is None:
            return
        if source.project_id != project_id:
            raise BadRequestError(
                message="This workspace does not belong to the project", details={}
            )
        if source.backend != "state":
            await self._purge_remote(ctx, source)
        await workspace_repo.delete(self.db, workspace=source)

    async def cleanup_project_copy(
        self, ctx: AuthContext, *, connection_id: UUID, key: str
    ) -> None:
        """Queue durable cleanup for a private copy left by a lost attempt."""
        await self._purge_remote(
            ctx,
            AgentWorkspace(
                organization_id=ctx.organization_id,
                connection_id=connection_id,
                scope_key=key,
                session_id=None,
            ),
        )

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
        """Delete the sandbox behind a workspace whose conversation or project is going.

        Both kinds are reached, and the cloud one matters more. A container has
        `sandboxd`'s TTL behind it, so failing here costs a host some disk until
        it sweeps. A Daytona sandbox has nothing behind it: this platform is the
        only thing that knows the conversation is gone, and the organization pays
        for the sandbox until somebody deletes it. This used to return early for
        anything that was not Docker, so that was never.

        The sandbox is destroyed once the deletion has committed, never before:
        a rollback after the destroy would restore rows naming files that no
        longer exist. Its connection is resolved now, while the transaction can
        still read the vault, and only the call is deferred.

        A tombstone goes into the same transaction (#2209). The rows naming the
        sandbox are deleted with it, so a destroy that fails - the provider
        down, the worker restarted between the commit and the call - used to
        leave nothing that knew the sandbox existed. The destroy removes the
        tombstone; `retry_pending_destroys` retries whatever is left.
        """
        if row.connection_id is None:
            return

        ref_id = row.session_id or row.scope_key
        pending = await pending_destroy_repo.add(
            self.db,
            organization_id=row.organization_id,
            connection_id=row.connection_id,
            ref_id=ref_id,
            scope_key=row.scope_key,
        )
        try:
            resolved = await self.connections.resolve_for_teardown(ctx, row.connection_id)
            sandbox = self._service_capability(resolved, row.scope_key)
        except Exception:
            # A service that is down must not stop a user deleting their chat.
            # The tombstone is committed with the deletion, and the sweep retries.
            logger.warning(
                "workspace_purge_failed", extra={"scope_key": row.scope_key}, exc_info=True
            )
            return
        # By the name it was opened under; attach-only, so a session already
        # gone is fine rather than one opened just to delete it.
        ref = WorkspaceRef(provider=_provider(sandbox), id=ref_id)
        spawn_after_commit(
            self.db,
            _destroy_and_forget(sandbox, ref, row.scope_key, pending.id),
            name="workspace-purge",
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
        recoveries = await workspace_repo.project_recovery_candidates(
            self.db, organization_id=ctx.organization_id
        )
        if recoveries:
            projects = await project_repo.get_many(
                self.db,
                [row.project_id for row in recoveries if row.project_id is not None],
                organization_id=ctx.organization_id,
            )
            visible = await accessible_ids(
                self.db, ctx, projects, Perm.PROJECTS_VIEW, resource_type=PROJECT
            )
            usable = await accessible_ids(
                self.db, ctx, projects, Perm.PROJECTS_USE, resource_type=PROJECT
            )
            rows.extend(row for row in recoveries if row.project_id in visible & usable)
            rows.sort(
                key=lambda row: row.last_used_at or datetime.min.replace(tzinfo=UTC), reverse=True
            )
        if not rows:
            return []
        agents = await agent_repo.get_many(
            self.db,
            [row.agent_id for row in rows if row.agent_id is not None],
            organization_id=ctx.organization_id,
        )
        titles = await conversation_repo.titles_for(
            self.db,
            [row.conversation_id for row in rows if row.conversation_id is not None],
            organization_id=ctx.organization_id,
        )
        # Only for the scopes where more than one chat reaches one workspace. A
        # conversation-scoped workspace has exactly one by construction, and
        # counting it would be a query answering a question nobody asked.
        owners = await self._owner_names(rows, organization_id=ctx.organization_id)
        shared = {
            row.agent_id
            for row in rows
            if row.scope in ("agent", "channel") and row.agent_id is not None
        }
        counts = (
            await conversation_repo.count_by_agent(
                self.db, list(shared), organization_id=ctx.organization_id
            )
            if shared
            else {}
        )
        overviews: list[WorkspaceOverview] = []
        for row in rows:
            agent = agents.get(row.agent_id) if row.agent_id is not None else None
            head = titles.get(row.conversation_id) if row.conversation_id is not None else None
            overviews.append(
                WorkspaceOverview(
                    row=row,
                    agent_name=(
                        (
                            agent.name
                            if agent is not None
                            else "Project files"
                            if row.project_id is not None
                            else "a deleted agent"
                        )
                        + (" (recovery copy)" if row.recovery_of_id is not None else "")
                    ),
                    agent_slug=agent.slug if agent is not None else "",
                    agent_has_avatar=agent.has_avatar if agent is not None else False,
                    conversation_title=head.title if head is not None else None,
                    conversation_is_callers=(
                        head is not None
                        and head.user_id is not None
                        and head.user_id == ctx.user_id
                    ),
                    conversations=(
                        1
                        if row.conversation_id is not None
                        else counts.get(row.agent_id, 0)
                        if row.scope in ("agent", "channel") and row.agent_id is not None
                        else 0
                    ),
                    access_label=access_label(row),
                    owner_name=owners.get(row.id),
                )
            )
        return overviews

    async def _owner_names(
        self, rows: list[AgentWorkspace], *, organization_id: UUID
    ) -> dict[UUID, str]:
        """Whose each of these workspaces is, by workspace id.

        One grouped query, like the agent names beside it. Only the refs that are
        UUIDs are looked up: the rest are platform ids for owners with no account
        here, and they are the answer rather than a failed lookup. A ref that
        names a UUID nobody in this organization holds resolves to nothing and
        the row says nothing - naming a stranger's email off an id would be the
        one read this listing must not do.
        """
        refs = {row.id: row.owner_ref for row in rows if row.owner_ref is not None}
        if not refs:
            return {}
        accounts: dict[UUID, UUID] = {}
        for workspace_id, ref in refs.items():
            with contextlib.suppress(ValueError):
                accounts[workspace_id] = UUID(ref)
        emails = await member_repo.get_emails_for_users(
            self.db, organization_id=organization_id, user_ids=list(set(accounts.values()))
        )
        named: dict[UUID, str] = {}
        for workspace_id, ref in refs.items():
            account = accounts.get(workspace_id)
            if account is None:
                named[workspace_id] = ref
                continue
            email = emails.get(account)
            if email is not None:
                named[workspace_id] = email
        return named

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
        rows: list[AgentWorkspace] = []
        for overview in overviews:
            row = overview.row
            if row.backend != "state":
                if not hosts:
                    continue
                if remote >= limit:
                    continue
                remote += 1
            rows.append(row)
        for row, contents in zip(rows, await self._entries_of(ctx, rows), strict=True):
            if contents.unreadable_reason is not None:
                unreadable += 1
                continue
            files = browsable([entry for entry in contents.entries if not entry.get("is_dir")])
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
        async with self._sharing_archives():
            return await self._flat_files(ctx, limit=limit)

    async def _flat_files(self, ctx: AuthContext, *, limit: int) -> FlatFileListing:
        overviews = await self.visible_to(ctx)
        files: list[FlatEntry] = []
        # A budget across the whole request, not per workspace: a host's thumbnail
        # is a `read_bytes` for that file, a stored one a decode of bytes already in
        # hand, and twenty-five workspaces of photographs would be a page that decodes
        # two hundred images to draw them 64 pixels wide. The tiles past it fall back
        # to the grey glyph.
        budget = THUMBNAIL_BUDGET
        opened = overviews[:limit]
        listed = await self._entries_of(ctx, [overview.row for overview in opened])
        readable: list[tuple[WorkspaceOverview, list[FileInfo]]] = [
            (
                overview,
                browsable([entry for entry in contents.entries if not entry.get("is_dir")]),
            )
            for overview, contents in zip(opened, listed, strict=True)
            if contents.unreadable_reason is None
        ]
        # Shared out in listing order before anything is fetched, so which tiles are
        # drawn does not depend on which host happened to answer first.
        shares: list[int] = []
        for _overview, entries in readable:
            picked, budget = thumbnail_picks(entries, budget)
            shares.append(len(picked))
        tiled = await _concurrently(
            [
                partial(self._tiles, ctx, overview.row, entries, share)
                for (overview, entries), share in zip(readable, shares, strict=True)
            ]
        )
        for (overview, entries), (previews, thumbnails, _left) in zip(readable, tiled, strict=True):
            files.extend(
                FlatEntry(
                    overview=overview,
                    info=entry,
                    preview=previews.get(str(entry.get("path"))),
                    thumbnail=thumbnails.get(str(entry.get("path"))),
                )
                for entry in entries
            )
        return FlatFileListing(
            files=files,
            workspaces_read=len(readable),
            unreadable=len(opened) - len(readable),
            truncated=len(overviews) > limit or any(contents.truncated for contents in listed),
        )

    async def _entries_of(
        self, ctx: AuthContext, rows: list[AgentWorkspace]
    ) -> list[WorkspaceContents]:
        """What each of several workspaces holds, in the order they were given.

        Concurrently, because a container-backed workspace is a walk of round trips
        to its host, and these listings used to make them one workspace after
        another - twenty-five walks end to end before the Workspaces page could draw
        anything. A host that will not answer still comes back as
        `unreadable_reason`, never as a raise, so one of them cannot fail the rest.
        """
        # `list_for_reader` leaves the stored files out; these are the ones read.
        await workspace_repo.load_files(self.db, rows)
        hosted: dict[UUID, list[int]] = {}
        answers: dict[int, WorkspaceContents] = {}
        for index, row in enumerate(rows):
            if row.backend == "state" or row.connection_id is None:
                answers[index] = await self._entries(ctx, row)
            else:
                hosted.setdefault(row.connection_id, []).append(index)
        # One `trees` request per host, where each workspace used to be a
        # connection and a request of its own - eighteen for one Documents page
        # on production, p50 2.3 s (#2248).
        batches = [
            indexes[start : start + MAX_TREES]
            for indexes in hosted.values()
            for start in range(0, len(indexes), MAX_TREES)
        ]
        listed = await _concurrently(
            [partial(self._host_trees, ctx, [rows[i] for i in batch]) for batch in batches]
        )
        for batch, contents in zip(batches, listed, strict=True):
            answers.update(zip(batch, contents, strict=True))
        return [answers[index] for index in range(len(rows))]

    async def _host_trees(
        self, ctx: AuthContext, rows: list[AgentWorkspace]
    ) -> list[WorkspaceContents]:
        """What each of several workspaces on one host holds, in one request to it.

        A host that cannot be asked at all makes every one of them unreadable,
        for the reason it gave; a workspace the host could not list is that
        workspace's own `unreadable_reason`, the rest still listed.
        """
        sessions = [row.session_id or row.scope_key for row in rows]
        try:
            async with self._archive(ctx, rows[0], timeout=_BROWSE_TIMEOUT_SECONDS) as archive:
                if archive is None:
                    return [WorkspaceContents(entries=[]) for _ in rows]
                trees = await _on_host_thread(
                    partial(
                        archive.trees,
                        sessions,
                        ".",
                        max_depth=_MAX_LISTED_DEPTH,
                        max_entries=_MAX_LISTED_ENTRIES,
                    )
                )
        except Exception as exc:
            logger.warning(
                "workspace_listing_failed",
                extra={"connection_id": str(rows[0].connection_id)},
                exc_info=True,
            )
            reason = _reason(exc)
            return [WorkspaceContents(entries=[], unreadable_reason=reason) for _ in rows]
        contents: list[WorkspaceContents] = []
        for session in sessions:
            tree = trees[session]
            if isinstance(tree, Exception):
                contents.append(WorkspaceContents(entries=[], unreadable_reason=_reason(tree)))
                continue
            if tree.truncated:
                logger.warning(
                    "workspace_listing_truncated",
                    extra={"session": session, "listed": len(tree.entries)},
                )
            contents.append(WorkspaceContents(entries=list(tree.entries), truncated=tree.truncated))
        return contents

    async def _host_thumbnails(
        self, ctx: AuthContext, row: AgentWorkspace, paths: list[str]
    ) -> dict[str, str]:
        """Thumbnails for a host's images, the ones :func:`thumbnail_picks` chose.

        A host's image is a `read_bytes` for that one file, which is why the pick
        checks the size *before* fetching, off the listing entry - a 20 MB
        photograph would be read in full to be thrown away by the scaler's own
        ceiling.

        Failure is silence. A file whose suffix says PNG and whose bytes are not
        one, or a host that stops answering mid-grid, leaves that tile with the
        glyph every container-backed image had before this existed.
        """
        tiles = await _concurrently(
            [partial(self._host_thumbnail, ctx, row, path) for path in paths]
        )
        return {path: tile for path, tile in zip(paths, tiles, strict=True) if tile is not None}

    async def _host_thumbnail(self, ctx: AuthContext, row: AgentWorkspace, path: str) -> str | None:
        """One host image drawn as a tile, or `None` for the glyph."""
        try:
            raw = await self._read_bytes_from(ctx, row, path)
        except Exception:
            logger.warning("workspace_thumbnail_unreadable", extra={"path": path})
            return None
        if raw is None:
            return None
        return await run_blocking(thumbnail_of, path, raw)

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

        Without tiles: the explorer that reads this draws a tree of names and
        sizes, so previews and thumbnails here were up to a budget of image reads
        and decodes per request that nothing displayed (#1930).

        Raises:
            NotFoundError: If it is not this organization's, or not one this
                caller may see. Reported as missing rather than refused in both
                cases, so an id cannot be used to find out which workspaces exist
                - in another organization, or in a colleague's conversation.
        """
        row = await self._workspace_of(ctx, workspace_id)
        return row, await self._browsable(ctx, row)

    async def _workspace_of(self, ctx: AuthContext, workspace_id: UUID) -> AgentWorkspace:
        """The workspace by its id, when this caller may read it - see :meth:`files_of`."""
        row = await workspace_repo.get(self.db, workspace_id, organization_id=ctx.organization_id)
        if row is None or not await self._may_read(ctx, row):
            raise NotFoundError(
                message="Workspace not found", details={"workspace_id": str(workspace_id)}
            )
        return row

    async def _conversation_workspace(
        self, ctx: AuthContext, conversation_id: UUID
    ) -> AgentWorkspace | None:
        """The workspace a conversation works in, if any - see :meth:`listing`."""
        return await workspace_repo.kept_for_conversation(
            self.db, organization_id=ctx.organization_id, conversation_id=conversation_id
        )

    async def _browsable(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        """A workspace's browsable entries, without tiles.

        What reading one file needs: whether the path is listed. Tiles are for a
        listing somebody looks at - drawing them before a read cost up to a
        budget of image reads and decodes to open a single file.
        """
        contents = await self._entries(ctx, row)
        return WorkspaceContents(
            entries=browsable(contents.entries),
            unreadable_reason=contents.unreadable_reason,
            truncated=contents.truncated,
        )

    async def _tiled(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        """A workspace's browsable entries, with what each file's tile draws."""
        contents = await self._browsable(ctx, row)
        previews, thumbnails, _budget = await self._tiles(
            ctx,
            row,
            [entry for entry in contents.entries if not entry.get("is_dir")],
            THUMBNAIL_BUDGET,
        )
        return replace(contents, previews=previews, thumbnails=thumbnails)

    async def _tiles(
        self, ctx: AuthContext, row: AgentWorkspace, files: list[FileInfo], budget: int
    ) -> tuple[dict[str, str], dict[str, str], int]:
        """Each file's preview and thumbnail, by path, and what is left of the budget.

        A stored workspace's bytes are in the row already, so every text file gets
        its first lines at no cost. A host's are a round trip per file, so it gets
        no previews - see :meth:`_host_thumbnails`.

        Images are drawn within `budget` on both backends. A stored image costs no
        fetch, but its decode is not free: about 48 compressed 4096x4096 PNGs fit
        under the stored cap, and drawing all of them was 800 megapixels decoded
        for one listing (#1930). The decode runs on the file pool rather than the
        event loop, so a grid of photographs does not hold every other request.
        """
        paths, budget = thumbnail_picks(files, budget)
        if row.backend == "state":
            stored = dict(row.files or {})
            previews: dict[str, str] = {}
            for entry in files:
                path = str(entry.get("path"))
                preview = stored_preview(stored.get(path))
                if preview is not None:
                    previews[path] = preview
            tiles = await _concurrently(
                [partial(run_blocking, stored_thumbnail, path, stored.get(path)) for path in paths]
            )
            thumbnails = {
                path: tile for path, tile in zip(paths, tiles, strict=True) if tile is not None
            }
            return previews, thumbnails, budget
        return {}, await self._host_thumbnails(ctx, row, paths), budget

    async def _may_read(self, ctx: AuthContext, row: AgentWorkspace) -> bool:
        """Whether this caller reaches one workspace by id.

        The same three predicates the listing applies, asked of one row - and asked
        here rather than only there, because a listing that hides a row and a route
        that serves it by id is not access control. The query is reused rather than
        reimplemented for exactly that reason: two copies of "who can see this"
        disagree eventually, and the one that is wrong is the one nobody reads.

        Normal project files are read through the project. Recovery copies are
        also discoverable here, but require both project view and use access;
        managing sandbox connections alone never grants access to a project.
        """
        if row.project_id is not None:
            if row.recovery_of_id is None:
                return False
            project = await project_repo.get(
                self.db, row.project_id, organization_id=ctx.organization_id
            )
            return (
                project is not None
                and await resolve_access(
                    self.db, ctx, project, Perm.PROJECTS_VIEW, resource_type=PROJECT
                )
                and await resolve_access(
                    self.db, ctx, project, Perm.PROJECTS_USE, resource_type=PROJECT
                )
            )
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
        row = await self._workspace_of(ctx, workspace_id)
        return await self._bytes_from(ctx, row, await self._browsable(ctx, row), path)

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
        row = await self._conversation_workspace(ctx, conversation_id)
        if row is None:
            raise NotFoundError(
                message="This conversation keeps no files",
                details={"conversation_id": str(conversation_id)},
            )
        return await self._bytes_from(ctx, row, await self._browsable(ctx, row), path)

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
                return await _on_host_thread(
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
        row = await self._workspace_of(ctx, workspace_id)
        contents = await self._browsable(ctx, row)
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
        row = await self._conversation_workspace(ctx, conversation_id)
        if row is None:
            return None
        return row, await self._tiled(ctx, row)

    async def _entries(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        if row.backend == "state":
            return WorkspaceContents(
                entries=stored_entries(dict(row.files or {}), row.directories or ())
            )
        return await self._remote_entries(ctx, row)

    @staticmethod
    async def _walk(archive: Any, session: str) -> tuple[list[FileInfo], bool]:
        """Every file on a host's volume, not only the ones at the root.

        **The archive's `ls` lists one directory.** It was called once, on the root,
        so a workspace whose files are all under `uploads/` reported a single
        directory entry and nothing else. Walking it with `ls` fixed that at a round
        trip per directory; `tree` is the same walk done by the service, on its own
        disk, in one request.

        Bounded twice over: by depth, because a workspace three deep is the shape
        this product produces, and by entries, because a host holding a
        `node_modules` must not turn a listing into ten thousand of them. A
        directory below the root that cannot be read is left out and marks the
        listing truncated; the root's failure is the host's and belongs to the
        caller, which turns it into `unreadable_reason`.

        Off the loop, because `WorkspaceArchive` is a synchronous `httpx.Client`:
        `flat_files` runs this for up to 25 workspaces in one request, so a blocking
        call would hold the loop for all 25 - and not only for that request. On
        `_HOST_CALLS` rather than `to_thread`, so a host that stops answering cannot
        take the default executor's threads; see there.

        Returns:
            What was found, and whether a bound or an unreadable directory left
            something out - because a listing that is shorter than the workspace
            and does not say so is one a person reads as complete.
        """
        tree = await _on_host_thread(
            partial(
                archive.tree,
                session,
                ".",
                max_depth=_MAX_LISTED_DEPTH,
                max_entries=_MAX_LISTED_ENTRIES,
            )
        )
        if tree.truncated:
            logger.warning(
                "workspace_listing_truncated",
                extra={"session": session, "listed": len(tree.entries)},
            )
        return list(tree.entries), tree.truncated

    async def _remote_entries(self, ctx: AuthContext, row: AgentWorkspace) -> WorkspaceContents:
        try:
            async with self._archive(ctx, row, timeout=_BROWSE_TIMEOUT_SECONDS) as archive:
                if archive is None:
                    return WorkspaceContents(entries=[])
                session = row.session_id or row.scope_key
                entries, truncated = await self._walk(archive, session)
                return WorkspaceContents(entries=entries, truncated=truncated)
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
        row = await self._conversation_workspace(ctx, conversation_id)
        if row is None:
            return None
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
        document = StateBackend(files=dict(row.files or {}), directories=row.directories or ())
        try:
            return document.read_bytes(path)
        except FileNotFoundError, IsADirectoryError, NotADirectoryError:
            return None

    @asynccontextmanager
    async def _sharing_archives(self) -> AsyncGenerator[None]:
        """Keep one archive - one HTTP pool - per host open until the block ends.

        A page that lists many workspaces and draws their thumbnails built a
        client, and so a connection, for every workspace and every image.
        """
        self._shared_archives = {}
        try:
            yield
        finally:
            archives, self._shared_archives = list(self._shared_archives.values()), None
            for archive in archives:
                await asyncio.to_thread(archive.close)

    @asynccontextmanager
    async def _archive(
        self, ctx: AuthContext, row: AgentWorkspace, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> AsyncGenerator[Any | None]:
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
        if self._shared_archives is not None:
            shared = self._shared_archives.get(row.connection_id)
            if shared is None:
                shared = WorkspaceArchive(
                    resolved.row.base_url, token=resolved.token, timeout=timeout
                )
                self._shared_archives[row.connection_id] = shared
            yield shared
            return
        archive = WorkspaceArchive(resolved.row.base_url, token=resolved.token, timeout=timeout)
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
        async with self._resolving:
            cached = self._connections_by_id.get(connection_id)
            if cached is None:
                cached = await self.connections.resolve(ctx, connection_id)
                self._connections_by_id[connection_id] = cached
            return cached


RETRY_BATCH = 20
"""Tombstones one sweep tick takes. Each is a call to a provider, held under a row lock."""

RETRY_CAP = timedelta(hours=6)
"""The longest pause between two attempts at one sandbox."""


_RETRY_CAP_EXPONENT = 9
"""2**9 minutes is past `RETRY_CAP` already, so no larger power is ever needed."""


def next_destroy_attempt(attempts: int, now: datetime) -> datetime:
    """When to try a sandbox again after `attempts` failures: 2, 4, 8 minutes, up to six hours.

    The exponent is capped before the `timedelta` is built (#2250): from about
    41 attempts `timedelta(minutes=2**attempts)` overflows, the row was never
    postponed, and as the oldest due row it aborted the sweep every minute for
    every tenant behind it.
    """
    exponent = min(attempts, _RETRY_CAP_EXPONENT)
    return now + min(timedelta(minutes=2**exponent), RETRY_CAP)


async def retry_pending_destroys() -> int:
    """Destroy the remote sandboxes a deletion could not, and forget each that goes (#2209).

    A sweep tick, run in the worker's process. Each tombstone is retried as the
    organization it belongs to, with no person behind it: resolving a
    connection reads that organization's vault and nothing else. A failure is
    logged and postponed rather than raised, so one provider that is down does
    not hold back another's sandboxes. Nothing gives up: a sandbox that still
    exists is still costing somebody. A connection switched off is still
    resolved for this, and one holding tombstones cannot be deleted.

    Returns:
        How many sandboxes this tick destroyed.
    """
    now = datetime.now(UTC)
    destroyed = 0
    async with get_db_context() as db:
        service = SandboxWorkspaceService(db)
        for pending in await pending_destroy_repo.claim_due(db, now=now, limit=RETRY_BATCH):
            ctx = AuthContext(user_id=None, organization_id=pending.organization_id, role="")
            try:
                resolved = await service.connections.resolve_for_teardown(
                    ctx, pending.connection_id
                )
                sandbox = service._service_capability(resolved, pending.scope_key)
                await sandbox.destroy(WorkspaceRef(provider=_provider(sandbox), id=pending.ref_id))
            except Exception:
                attempts = pending.attempts + 1
                logger.warning(
                    "workspace_purge_retry_failed",
                    extra={"scope_key": pending.scope_key, "attempts": attempts},
                    exc_info=True,
                )
                await pending_destroy_repo.postpone(
                    db, pending.id, attempts=attempts, until=next_destroy_attempt(attempts, now)
                )
                continue
            await pending_destroy_repo.remove(db, pending.id)
            destroyed += 1
    return destroyed


async def _destroy_and_forget(
    sandbox: SandboxdWorkspace | DaytonaWorkspace,
    ref: WorkspaceRef,
    scope_key: str,
    pending_id: UUID,
) -> None:
    """Destroy a sandbox whose rows are gone, and drop its tombstone once it is.

    A host that is down is logged, not raised: the tombstone stays, and the
    sweep tries again.
    """
    try:
        await sandbox.destroy(ref)
    except Exception:
        logger.warning("workspace_purge_failed", extra={"scope_key": scope_key}, exc_info=True)
        return
    async with get_db_context() as db:
        await pending_destroy_repo.remove(db, pending_id)


def _absent(row: AgentWorkspace, contents: WorkspaceContents, path: str) -> bool:
    """Whether a listing that could be read says this path is not in it.

    Only asked of a workspace kept on a host. A stored one answers from its own
    document, so a listing is never its oracle. An unreadable listing answers
    `False`: it knows nothing, and a "no such file" built on it would be a
    confident wrong answer.
    """
    if row.backend == "state":
        return False
    if contents.unreadable_reason is not None or not contents.entries:
        return False
    return all(str(entry.get("path")) != path for entry in contents.entries)


def stored_entries(files: dict[str, FileData], directories: Sequence[str] = ()) -> list[FileInfo]:
    """Every file in a stored workspace, dotfiles included.

    Read from the document's own keys rather than a glob, so `/​.env` and `/​.gitignore` are
    listed like any other file: a listing that claims to be "what the agent is
    keeping" cannot quietly omit a class of filename.

    A file *inside* a dot-directory (`/​.git/config`) is left out, and that is the one
    omission worth keeping: an agent that ran `git init` would otherwise fill the
    panel with object files nobody asked to see.
    """
    document = StateBackend(files=files)
    entries = [
        FileInfo(
            name=PurePosixPath(path).name,
            path=path,
            is_dir=False,
            size=document.size(path),
            modified_at=data.get("modified_at"),
        )
        for path, data in files.items()
        if not any(part.startswith(".") for part in PurePosixPath(path).parent.parts)
    ]
    entries.extend(
        FileInfo(name=PurePosixPath(path).name, path=path, is_dir=True, size=0)
        for path in directories
        if path != "/" and not any(part.startswith(".") for part in PurePosixPath(path).parts)
    )
    return sorted(entries, key=lambda entry: entry["path"])


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

THUMBNAIL_BUDGET = 24
"""How many images one listing will decode to draw, on either backend.

A host's image is a `read_bytes` per file; a stored one is already in the document
the listing reads, but decoding it is still the expensive half. Twenty-four is one
screen of tiles - past it the grey glyph is drawn instead."""

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
    except BinasciiError, ValueError:
        logger.warning("workspace_thumbnail_undecodable", extra={"path": path})
        return None
    return thumbnail_of(path, raw)


def thumbnail_picks(entries: list[FileInfo], budget: int) -> tuple[list[str], int]:
    """Which images a listing will draw, and the budget left.

    Bounded on both backends - see :data:`THUMBNAIL_BUDGET`. The size is checked
    *before* anything is fetched or decoded, off the listing entry: a 20 MB
    photograph would be read in full to be thrown away by the scaler's own ceiling.
    """
    picked: list[str] = []
    for entry in entries:
        if budget <= 0:
            break
        path = str(entry.get("path"))
        if PurePosixPath(path).suffix.lower() not in THUMBNAIL_SUFFIXES:
            continue
        size = entry.get("size")
        if size is None or int(size) > THUMBNAIL_SOURCE_LIMIT:
            continue
        budget -= 1
        picked.append(path)
    return picked, budget


def thumbnail_of(path: str, raw: bytes) -> str | None:
    """An image's bytes scaled to a data URI, wherever they came from.

    Split out of `stored_thumbnail` so a container-backed file can be drawn too.
    A stored one arrives base64 in the document the listing already read; a host's
    is a `read_bytes` per file, which is why the caller counts them - see
    `_host_thumbnails`.

    Whether the suffix says image at all is asked by each caller instead, because
    each pays a different price for the answer: a decode of the whole base64 body
    for a stored file, a fetch from the host for a container's.
    """
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
    if row.scope == "project":
        return "Everybody the project is shared with"
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
    if row.scope == "project":
        return "This project, shared by every chat in it"
    return "This run only"
