"""Where sandboxes run, as a client sees it.

No field here carries a credential. `secret_id` is a reference the vault resolves
under its own permission check, which is the only shape a token that can run
commands on a host may take in a response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.urls import ServiceAddress


class SandboxConnectionCreate(BaseSchema):
    """Register a place an organization's sandboxes run."""

    name: str = Field(min_length=1, max_length=128, description="What operators call this host")
    kind: Literal["docker", "daytona"] = Field(
        description=(
            "docker: a sandboxd service on a host you run. "
            "daytona: cloud sandboxes on this organization's own Daytona account."
        )
    )
    base_url: ServiceAddress | None = Field(
        default=None,
        max_length=512,
        description="Where the sandbox service answers, e.g. http://sandboxd:8080. Container only.",
    )
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault entry holding the service token or Daytona key. An id, never "
            "a value: whoever holds this credential can run commands on that host."
        ),
    )
    default_runtime: str | None = Field(
        default=None,
        max_length=64,
        description="Alias an agent gets when its spec names none; null takes the service's own",
    )
    is_default: bool = Field(
        default=False,
        description="Whether an agent that names no connection resolves to this one",
    )


class SandboxConnectionUpdate(BaseSchema):
    """Change one. Every field optional; unset means unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: Literal["docker", "daytona"] | None = None
    base_url: ServiceAddress | None = Field(default=None, max_length=512)
    secret_id: UUID | None = None
    default_runtime: str | None = Field(default=None, max_length=64)
    is_default: bool | None = None
    is_active: bool | None = None


class SandboxConnectionRead(BaseSchema, TimestampSchema):
    id: UUID
    name: str
    kind: str
    base_url: str | None = None
    secret_id: UUID | None = None
    default_runtime: str | None = None
    is_default: bool
    is_active: bool


class SandboxConnectionList(BaseSchema):
    items: list[SandboxConnectionRead]
    total: int


class SandboxLocalServiceRead(BaseSchema):
    """Whether this deployment is already running a sandbox service of its own.

    Answered by asking, not by configuration: the address a container service
    answers on is a row per organization rather than a setting, so the only honest
    way to offer one is to try the address this project's own compose file gives it
    and report what happened.
    """

    url: str | None = Field(
        default=None,
        description="Where a service answered, or null if none did. Prefill, not a decision.",
    )
    token_available: bool = Field(
        default=False,
        description=(
            "Whether this deployment's environment carries the token that service "
            "was started with, so it can be stored in the vault without anybody "
            "having to find it."
        ),
    )
    registered_connection_id: UUID | None = Field(
        default=None,
        description="The connection already pointing at that address, if this organization has one",
    )


class SandboxLocalCredentialRead(BaseSchema):
    """The vault entry holding this deployment's own service token.

    An id and four characters, like every other answer about a stored secret. The
    token itself was already in this deployment's environment and stays there; what
    this reports is that it now also lives where a connection can name it.
    """

    secret_id: UUID
    name: str
    hint: str


class SandboxRuntimeOption(BaseSchema):
    """One runtime the sandbox library ships, offered before anything is asked.

    Separate from `SandboxRuntimeRead`, which is what a *service* says it allows.
    This is the catalog every `sandboxd` is built from, so a form can offer it with
    no address, no credential and no round trip - and `allowed` is left for the
    probe to fill in, because whether a particular service permits an alias is a
    question only that service answers.
    """

    alias: str
    description: str = ""
    image: str | None = Field(
        default=None, description="What it runs, ready-made or the base a build starts from"
    )
    builds: bool = Field(
        default=False,
        description="Whether the first session builds an image, which is slower once and cached after",
    )


class SandboxRuntimeCatalog(BaseSchema):
    """Every runtime the library ships. Static - no host is contacted to answer."""

    items: list[SandboxRuntimeOption] = Field(default_factory=list)
    total: int = 0


class SandboxProbeRequest(BaseSchema):
    """Ask a service what it allows, before a connection exists to name it.

    The pair of fields the answer depends on, and nothing else: an address that has
    not been saved yet and a vault entry that has. Never a token - a form that
    posted one would have had it in a browser.
    """

    base_url: ServiceAddress = Field(min_length=1, max_length=512)
    secret_id: UUID | None = Field(
        default=None, description="The vault entry holding the service token"
    )


class SandboxRuntimeRead(BaseSchema):
    """One runtime the service allows, with the ceilings actually in force.

    Read from the service rather than stored here. These are its boot
    configuration, so a copy would disagree the first time an operator restarted
    it with a different limit - and the Builder needs the live answer anyway,
    because an alias this names is an alias the service will accept.
    """

    alias: str
    image: str | None = None
    description: str = ""
    builds: bool = False
    mem_limit: str | None = None
    cpus: float | None = None
    network_mode: str | None = None


class SandboxPolicyRead(BaseSchema):
    """What a connection's service allows, as an operator and the Builder read it."""

    kind: str
    runtimes: list[SandboxRuntimeRead] = Field(default_factory=list)
    default_runtime: str | None = None
    max_sessions: int | None = None
    max_open_sessions: int | None = None
    max_sessions_per_tenant: int | None = None
    idle_timeout: int | None = None
    workspace_root: str | None = None
    persist_containers: bool | None = None


class SandboxSessionUsage(BaseSchema):
    """What one sandbox is using, sampled from the host.

    Named fields rather than the daemon's mapping. `usage_report.py` read
    `sampled.get("memory_bytes")` off a `dict[str, Any]`, so the two keys it
    depends on were unchecked in the one place a rename would show up as a
    missing number rather than as an error (#562). Every field is optional
    because a sample can fail for one sandbox while the rest answer.

    The field list is the whole of what a caller is told, since a model drops
    what it does not declare - so a value the daemon starts reporting has to be
    added here as well as read. `pids` is declared for that reason and no other:
    nothing renders it yet, but it is in the contract
    `sandbox-connections-api.ts` publishes, and the mapping this replaced
    carried it.
    """

    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None
    cpu_percent: float | None = None
    pids: int | None = None


class SandboxSessionRead(BaseSchema):
    """One sandbox open on a connection, as an operator reads it.

    The attribution fields are filled from `agent_workspaces` rather than by
    decoding the session id. A `run`-scoped session has no row - it is deleted
    the moment the run ends - so they are absent for one, which is normal.
    """

    session_id: str
    runtime: str
    alive: bool
    state: str = "running"
    created_at: float
    last_activity: float
    idle_seconds: float
    usage: SandboxSessionUsage | None = None
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    conversation_is_callers: bool = False
    """Whether the linked conversation belongs to whoever is reading this.

    The chat page lists its *owner's* threads, so a link offered to anybody else
    lands on an empty sidebar dressed as the conversation - and an operator reads
    this listing precisely because it is organization-wide, so most rows are
    somebody else's. The workspace listing already answers this question; a
    sessions row that did not was a dead link on most of the page.
    """
    scope: str | None = None


class SandboxSessionList(BaseSchema):
    """This organization's sandboxes on one connection, and the host's ceilings.

    `tenant` is deliberately absent from the rows: every one of them is this
    organization's, because the service is asked for all of them and the ones
    belonging to other tenants are dropped before this is built.

    `host_session_count` and `host_open_count` are the two host-wide numerators
    that make `limit` and `open_limit` dividable, the way `len(sessions)` already
    divides against `tenant_limit`. They count every tenant on the host, taken
    before the tenant filter, so a caller refused a session while under their own
    ceiling can see the host itself is full rather than reading the daemon's logs.
    Two aggregate integers naming nothing - a long way from the rows the filter
    withholds - and the route is gated on `connections:view`, the authority to
    watch a host rather than any member's. `None` on a Daytona connection, which
    enforces no ceilings of ours and so has no counts to divide, matching how
    `limit`/`open_limit`/`tenant_limit` are already `None` there.
    """

    sessions: list[SandboxSessionRead] = Field(default_factory=list)
    kind: Literal["docker", "daytona"] = Field(
        description="Which sort of host answered, so an empty daytona listing is told apart from an idle docker one",
    )
    limit: int | None = None
    open_limit: int | None = None
    tenant_limit: int | None = None
    host_session_count: int | None = Field(
        default=None,
        description="Resident sandboxes host-wide, before the tenant filter; the numerator for `limit`.",
    )
    host_open_count: int | None = Field(
        default=None,
        description="Open sessions host-wide (resident and hibernated); the numerator for `open_limit`.",
    )


class SandboxEventRead(BaseSchema):
    """One operation performed against a sandbox.

    Never file contents and never command output - the service does not record
    them, which is what keeps an activity log from becoming a way to read another
    agent's work.
    """

    seq: int
    at: float
    op: str
    target: str
    ok: bool
    detail: str = ""
    duration_ms: float = 0.0


class SandboxOperationRead(BaseSchema):
    """One operation this platform recorded, from its own table rather than the
    service's buffer.

    The two extra fields are the whole reason the table exists: `agent_name` and
    `run_id` are what the service cannot know, and they are what somebody auditing
    a sandbox actually asks. Never file contents and never command output - see the
    model's own docstring.
    """

    id: UUID
    at: datetime
    op: str
    target: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0
    session_key: str
    agent_id: UUID | None = None
    agent_name: str | None = None
    run_id: UUID | None = None


class SandboxOperationList(BaseSchema):
    """One page of the log, and what the page is of.

    `total` is what makes the pager honest - the service's own log could only say
    how much of its 200-entry buffer was left. `operations` is the vocabulary the
    log actually holds, so the filter offers what is there rather than every method
    a backend could have.
    """

    items: list[SandboxOperationRead] = Field(default_factory=list)
    total: int = 0
    operations: list[str] = Field(default_factory=list)


class SandboxEventList(BaseSchema):
    events: list[SandboxEventRead] = Field(default_factory=list)
    latest_seq: int = 0
    """Pass back as `after` to poll without re-reading the whole log."""
