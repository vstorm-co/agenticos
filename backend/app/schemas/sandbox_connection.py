"""Where sandboxes run, as a client sees it.

No field here carries a credential. `secret_id` is a reference the vault resolves
under its own permission check, which is the only shape a token that can run
commands on a host may take in a response.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import AfterValidator, Field

from app.schemas.base import BaseSchema, TimestampSchema

_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "metadata",
        "instance-data",
    }
)
"""Names that only ever mean a cloud instance-metadata service.

Blocked by name as well as by address because a name is what somebody types and
`169.254.169.254` is what it resolves to. Neither is ever a `sandboxd`.
"""


def _service_address(value: str) -> str:
    """Refuse an address the platform must not be asked to fetch.

    This is not decoration. `SandboxConnectionService._get_json` performs a
    server-side GET against whatever is stored or probed here, with the
    connection's token attached, and hands the JSON body back to the caller - so
    an unvalidated string turns the API container into a fetch proxy for its own
    network, which is precisely the boundary `sandboxd` exists to draw. A holder
    of `connections:manage` is an organization operator, not the person who runs
    the deployment.

    What is refused, and why only this much:

    * **A scheme that is not http(s).** `httpx` has no transport for `file://` or
      `gopher://` so they fail anyway, but failing on a validator with a sentence
      beats failing on a stack trace.
    * **A missing host**, which is a typo rather than an attack, and would
      otherwise be fetched as a relative path against an empty base.
    * **Link-local addresses and the metadata hostnames**, because
      `169.254.169.254` and `metadata.google.internal` are never a sandbox
      service and are the one target where a single unauthenticated GET is worth
      something to an attacker.

    **RFC1918 is deliberately still allowed.** The legitimate address of a
    sandbox service *is* private - `http://sandboxd:8080` inside compose,
    `http://localhost:8080` for a developer running the API on their host - so a
    private-range denylist would refuse this project's own documented setup. That
    means this validator narrows the hole rather than closing it: a name that
    resolves to something internal still resolves, and DNS rebinding is not
    addressed here. The boundary that actually holds is `connections:manage` plus
    whatever egress policy the deployment puts around the API container;
    `docs/configuration.md` says so where it belongs.
    """
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("A sandbox service address must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise ValueError("A sandbox service address must name a host")
    if host.lower() in _METADATA_HOSTS:
        raise ValueError("That host is an instance-metadata service, not a sandbox service")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name rather than a literal, which is the common case and cannot be
        # judged without resolving it - see the note about rebinding above.
        return value
    if address.is_link_local:
        raise ValueError("A link-local address is never a sandbox service")
    return value


ServiceAddress = Annotated[str, AfterValidator(_service_address)]
"""An address this platform is willing to make a server-side request to.

One alias for all three schemas that carry one: a connection being created, one
being edited, and one being probed before a row exists. Three copies of the rule
would be three chances for the probe - the only one that takes an address
straight from a request body - to be the one that missed it.
"""


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
