"""Every kind of background job, what it carries and where it runs (#2219).

A service enqueues one of these with `app.services.background_jobs.enqueue`;
a worker runs it with the handler `app/worker/handlers.py` binds to its kind.
The split is deliberate: this module imports Pydantic and nothing else, so a
route that queues an ingestion does not import the parser that will run it.

Attempts follow one rule (decided for #2219): three by default, two for
ingestion - a parse that failed twice will fail a third time, and each try
costs embeddings - and one for a scheduled sweep, whose next tick is its retry.
An attempt is spent at the claim, so a job that kills its worker spends one
too; see `app.db.models.background_job`.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Pool(enum.StrEnum):
    """Which workers run a job. Each pool has its own concurrency, so one cannot starve another."""

    AGENT = "agent"
    """Agent runs: long, waiting on models, cheap in memory."""
    INGEST = "ingest"
    """Parsing and embedding: CPU and memory heavy, each job in a child process."""
    SYSTEM = "system"
    """Sweeps, cleanups and reports: short, and nearly always idle."""


class Priority(enum.IntEnum):
    """Within a pool, lower goes first."""

    INTERACTIVE = 0
    SCHEDULED = 1
    BULK = 2


class Payload(BaseModel):
    """What a job carries: identifiers and primitives, never a row or a session."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NoPayload(Payload):
    """For a job whose work is to look at the current state."""


class Tick(Payload):
    """A scheduled job: the occurrence it was fired for, the same on every attempt."""

    scheduled_for: datetime


class IngestDocument(Payload):
    rag_document_id: UUID
    collection_name: str
    filepath: str
    source_path: str
    replace: bool
    attempt: int
    """Which dispatch of the document this is (#1598) - not the job's attempt."""


class SyncCollection(Payload):
    sync_log_id: UUID
    source: str
    collection_name: str
    mode: str
    path: str
    knowledge_base_id: UUID | None


class SyncConnectorSource(Payload):
    source_id: UUID
    sync_log_id: UUID | None


def sync_source_key(source_id: UUID) -> str:
    """What every sync of one source shares: one queued at a time, one running at a time."""
    return f"sync-source:{source_id}"


class FireTrigger(Payload):
    trigger_id: UUID
    event_context: str | None = None
    claimed_at: datetime | None = None
    """The `fire_in_flight_since` the scheduled claim stamped - its claim ticket."""


class RunAgent(Payload):
    """An asynchronous `POST /agents/{id}/run`: who asked, and what they sent."""

    agent_id: UUID
    organization_id: UUID
    user_id: UUID
    api_key_id: UUID | None
    """The key that asked, so the worker re-establishes its narrowed context; `None` for a session."""
    prompt: str
    conversation_id: UUID
    environment_id: UUID | None
    file_ids: list[UUID]
    digest: str
    """The request's fingerprint: an idempotent retry must send the same one."""


class ThinkForPerson(Payload):
    """One person in one organization, for the platform's nightly look at their week (#2301)."""

    organization_id: UUID
    user_id: UUID


class LookThroughWatch(Payload):
    """One person's watch over one of their connections, due for a look (#2301)."""

    watch_id: UUID


class InstallRolePack(Payload):
    """The routines of a role pack, to create for the person who accepted it (#2301)."""

    organization_id: UUID
    user_id: UUID
    pack_id: str


class WelcomeMember(Payload):
    """Somebody who just joined, to greet in the chat apps the organization connected (#2301)."""

    organization_id: UUID
    user_id: UUID


class Restamp(Payload):
    collection: str
    organization_id: UUID
    knowledge_base_id: UUID


class CleanupExternalState(Payload):
    storage_paths: list[str]
    collections: list[str]
    restamps: list[Restamp]
    # Defaulted, so a job queued by a release before it existed still parses; and
    # left out of the dump when empty, so a worker from that release (whose payload
    # forbids extra fields) still runs every cleanup that carries none. Only an
    # organization purge carries prefixes, and only a current worker runs it.
    prefixes: list[str] = Field(default_factory=list, exclude_if=lambda prefixes: not prefixes)
    """Storage prefixes removed whole - an organization's generated media (#2310)."""
    required_paths: list[str] = Field(
        default_factory=list, exclude_if=lambda required_paths: not required_paths
    )
    """Files whose failed unlink fails the job, so it is retried - generated media
    whose rows went with the delete that queued this (#2310). Defaulted and left
    out of the dump when empty, as `prefixes` is. A previous-release worker
    refuses a job that carries them; a current one runs it."""


@dataclass(frozen=True)
class TaskKind:
    """What a worker needs to know about a claimed job: where it runs, for how long, how often."""

    kind: str
    payload_type: type[Payload]
    pool: Pool
    max_attempts: int
    timeout: timedelta
    priority: Priority
    # Whether an administrator may withdraw a queued job of this kind. Not when a
    # row outside the queue - a document, a sync log - waits in `processing` for
    # the job to settle it: cancelled, nothing ever would.
    cancellable: bool = True


@dataclass(frozen=True)
class Task[P: Payload](TaskKind):
    """One kind of job, typed by its payload, as a service enqueues it."""

    payload_type: type[P]

    def dump(self, payload: P) -> dict[str, JsonValue]:
        return payload.model_dump(mode="json")

    def load(self, raw: dict[str, JsonValue]) -> P:
        return self.payload_type.model_validate(raw)


def _sweep(
    kind: str, *, timeout: timedelta = timedelta(minutes=15), max_attempts: int = 1
) -> Task[Tick]:
    return Task(
        kind=kind,
        payload_type=Tick,
        pool=Pool.SYSTEM,
        max_attempts=max_attempts,
        timeout=timeout,
        priority=Priority.SCHEDULED,
    )


INGEST_DOCUMENT = Task(
    kind="ingest-document",
    payload_type=IngestDocument,
    pool=Pool.INGEST,
    max_attempts=2,
    timeout=timedelta(hours=1),
    priority=Priority.INTERACTIVE,
    cancellable=False,
)
SYNC_COLLECTION = Task(
    kind="sync-collection",
    payload_type=SyncCollection,
    pool=Pool.INGEST,
    max_attempts=2,
    timeout=timedelta(hours=4),
    priority=Priority.BULK,
    cancellable=False,
)
SYNC_SOURCE = Task(
    kind="sync-source",
    payload_type=SyncConnectorSource,
    pool=Pool.INGEST,
    max_attempts=2,
    timeout=timedelta(hours=4),
    priority=Priority.BULK,
    cancellable=False,
)
# One attempt, for the reason `RUN_AGENT` below has one: a fire is an agent run,
# and a worker that died under it may already have paid for its model calls and
# made its tools' side effects. The dead job waits on Admin -> Background jobs,
# where somebody who knows what the run did can retry it.
FIRE_TRIGGER = Task(
    kind="fire-trigger",
    payload_type=FireTrigger,
    pool=Pool.AGENT,
    max_attempts=1,
    timeout=timedelta(hours=3),
    priority=Priority.SCHEDULED,
)
# One attempt: a run a worker died under has already spent, and a second would
# run the agent again - its model calls and its tools' side effects with it. The
# caller reads `failed` and decides; that is what idempotency keys are for.
RUN_AGENT = Task(
    kind="run-agent",
    payload_type=RunAgent,
    pool=Pool.AGENT,
    max_attempts=1,
    timeout=timedelta(hours=3),
    priority=Priority.INTERACTIVE,
)
# One attempt: it is a model call booked to the person's proactivity limit, and
# the next night is the retry - nothing a person asked for waits on it.
THINK_FOR_PERSON = Task(
    kind="think-for-person",
    payload_type=ThinkForPerson,
    pool=Pool.AGENT,
    max_attempts=1,
    timeout=timedelta(minutes=10),
    priority=Priority.BULK,
)
# One attempt, like the nightly look: a model call on the person's limit, and the
# watch's next look is the retry.
LOOK_THROUGH_WATCH = Task(
    kind="look-through-watch",
    payload_type=LookThroughWatch,
    pool=Pool.AGENT,
    max_attempts=1,
    timeout=timedelta(minutes=10),
    priority=Priority.BULK,
)
# One attempt, like the welcome: a direct message sent twice is worse than one
# the next morning's briefing catches up on.
BRIEF_PERSON = Task(
    kind="brief-person",
    payload_type=ThinkForPerson,
    pool=Pool.SYSTEM,
    max_attempts=1,
    timeout=timedelta(minutes=5),
    priority=Priority.SCHEDULED,
)
# Three: creating a routine is idempotent per pack (a routine already made from
# the same template is not made twice), and the person clicked and is waiting.
INSTALL_ROLE_PACK = Task(
    kind="install-role-pack",
    payload_type=InstallRolePack,
    pool=Pool.SYSTEM,
    max_attempts=3,
    timeout=timedelta(minutes=5),
    priority=Priority.INTERACTIVE,
)
# One: a greeting is best-effort, and a retry would greet the person a second
# time on every platform that had already succeeded. A platform that fails is
# logged and the others still try, inside the one attempt.
WELCOME_MEMBER = Task(
    kind="welcome-member",
    payload_type=WelcomeMember,
    pool=Pool.SYSTEM,
    max_attempts=1,
    timeout=timedelta(minutes=5),
    priority=Priority.SCHEDULED,
)
CLEANUP_EXTERNAL_STATE = Task(
    kind="cleanup-external-state",
    payload_type=CleanupExternalState,
    pool=Pool.SYSTEM,
    max_attempts=3,
    timeout=timedelta(minutes=30),
    priority=Priority.SCHEDULED,
)

CHECK_AGENT_TRIGGERS = _sweep("check-agent-triggers")
POLL_PORTAL_GRANTS = _sweep("poll-portal-grants")
DELIVER_NOTIFICATIONS = _sweep("deliver-notifications")
DISPATCH_DUE_SYNCS = _sweep("dispatch-due-syncs")
RETRY_SANDBOX_DESTROYS = _sweep("retry-sandbox-destroys")
SWEEP_SANDBOX_OPERATIONS = _sweep("sweep-sandbox-operations")
SWEEP_MCP_CONNECTIONS = _sweep("sweep-mcp-connections")
EXPIRE_APPROVALS = _sweep("expire-approvals")
EXPIRE_INVITATIONS = _sweep("expire-invitations")
REAP_STALE_RUNS = _sweep("reap-stale-runs")
SWEEP_TEARDOWN_RESERVATIONS = _sweep("sweep-teardown-reservations")
APPLY_RETENTION = _sweep("apply-retention", timeout=timedelta(hours=2))
SWEEP_NOTIFICATIONS = _sweep("sweep-notifications")
SWEEP_BACKGROUND_JOBS = _sweep("sweep-background-jobs")
REAP_VOICE_CALLS = _sweep("reap-voice-calls")
SWEEP_GENERATED_MEDIA = _sweep("sweep-generated-media")
PROACTIVE_SWEEP = _sweep("proactive-sweep")
WATCH_SWEEP = _sweep("watch-sweep")
# Three attempts, unlike the sweeps above: a sweep's next tick is the same work
# again, but the next report is a week or a month away and covers another window,
# so an occurrence lost to a deploy or an outage was never sent. Each occurrence
# is idempotent across attempts (Codex, #2248).
WEEKLY_USAGE_REPORT = _sweep("weekly-usage-report", timeout=timedelta(hours=1), max_attempts=3)
MONTHLY_USAGE_REPORT = _sweep("monthly-usage-report", timeout=timedelta(hours=1), max_attempts=3)

TASKS: dict[str, TaskKind] = {
    task.kind: task
    for task in (
        INGEST_DOCUMENT,
        SYNC_COLLECTION,
        SYNC_SOURCE,
        FIRE_TRIGGER,
        RUN_AGENT,
        THINK_FOR_PERSON,
        LOOK_THROUGH_WATCH,
        BRIEF_PERSON,
        INSTALL_ROLE_PACK,
        WELCOME_MEMBER,
        CLEANUP_EXTERNAL_STATE,
        CHECK_AGENT_TRIGGERS,
        POLL_PORTAL_GRANTS,
        DELIVER_NOTIFICATIONS,
        DISPATCH_DUE_SYNCS,
        RETRY_SANDBOX_DESTROYS,
        SWEEP_SANDBOX_OPERATIONS,
        SWEEP_MCP_CONNECTIONS,
        EXPIRE_APPROVALS,
        EXPIRE_INVITATIONS,
        REAP_STALE_RUNS,
        SWEEP_TEARDOWN_RESERVATIONS,
        APPLY_RETENTION,
        SWEEP_NOTIFICATIONS,
        SWEEP_BACKGROUND_JOBS,
        REAP_VOICE_CALLS,
        SWEEP_GENERATED_MEDIA,
        PROACTIVE_SWEEP,
        WATCH_SWEEP,
        WEEKLY_USAGE_REPORT,
        MONTHLY_USAGE_REPORT,
    )
}
"""Every kind, by name: what a worker looks a claimed job up in."""
