"""Where sandboxes run, as a client sees it.

No field here carries a credential. `secret_id` is a reference the vault resolves
under its own permission check, which is the only shape a token that can run
commands on a host may take in a response.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema


class SandboxConnectionCreate(BaseSchema):
    """Register a place an organization's sandboxes run."""

    name: str = Field(min_length=1, max_length=128, description="What operators call this host")
    kind: Literal["docker", "daytona"] = Field(
        description=(
            "docker: a sandboxd service on a host you run. "
            "daytona: cloud sandboxes on this organization's own Daytona account."
        )
    )
    base_url: str | None = Field(
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
    base_url: str | None = Field(default=None, max_length=512)
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

    base_url: str = Field(min_length=1, max_length=512)
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
    usage: dict[str, float | int | None] | None = None
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    scope: str | None = None


class SandboxSessionList(BaseSchema):
    """This organization's sandboxes on one connection, and the host's ceilings.

    `tenant` is deliberately absent from the rows: every one of them is this
    organization's, because the service is asked for all of them and the ones
    belonging to other tenants are dropped before this is built.
    """

    sessions: list[SandboxSessionRead] = Field(default_factory=list)
    limit: int | None = None
    open_limit: int | None = None
    tenant_limit: int | None = None


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


class SandboxEventList(BaseSchema):
    events: list[SandboxEventRead] = Field(default_factory=list)
    latest_seq: int = 0
    """Pass back as `after` to poll without re-reading the whole log."""
