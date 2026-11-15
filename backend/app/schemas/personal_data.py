"""What a person's own data looks like on the wire."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.routine_actions import RoutineConsent
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.telephony import PhoneContactConfig


class RoutineAnswerExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    organization_id: UUID
    trigger_id: UUID
    answer: str
    status: Literal["pending", "delivered", "unavailable", "run_log", "no_answer"]
    conversation_id: UUID | None
    created_at: datetime
    updated_at: datetime | None


class RoutineDeviceWaitExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    trigger_id: UUID
    device_id: UUID
    status: Literal["waiting", "started", "cancelled", "expired", "failed"]
    event_context: str | None
    reason: str | None
    admission_failures: int
    created_at: datetime
    finished_at: datetime | None


class RoutineHealthExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    trigger_id: UUID | None
    watch_id: UUID | None
    activation_at: datetime
    healthy: bool


class RoutineSourceExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    approved_sources: RoutineSourcePolicy | None
    action_consents: list[RoutineConsent] = Field(default_factory=list)


class ProjectTrackingExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    table_id: UUID
    trigger_id: UUID


class PhoneContactExport(PhoneContactConfig):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID


class PhoneCaseAttemptExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    phone_attempted_at: datetime


class OutcomeExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    kind: str
    dedupe_key: str
    summary: str
    context_url: str | None
    status: str
    source_run_id: UUID | None
    source_conversation_id: UUID | None
    phone_attempted_at: datetime | None
    last_observed_at: datetime | None
    last_recovered_at: datetime | None
    settled_at: datetime | None
    settled_via: str | None
    created_at: datetime
    updated_at: datetime | None


class PhoneCallExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    endpoint_id: UUID
    agent_id: UUID | None
    agent_version_id: UUID | None
    source_run_id: UUID | None
    source_conversation_id: UUID | None
    conversation_id: UUID | None
    mode: str
    direction: str
    status: str
    destination: str | None
    report: str | None
    purpose: str
    outcome_id: UUID | None
    importance_reason: str | None
    not_before: datetime | None
    report_language: str
    cap_seconds: int
    end_reason: str | None
    estimated_cost_usd: Decimal
    created_at: datetime
    finished_at: datetime | None


class CodingTaskChangeExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    conversation_id: UUID
    tool_call_id: str | None
    harness: str
    files: list[dict[str, object]]
    omitted: int
    truncated: bool
    created_at: datetime


class ConnectedAccountExport(BaseModel):
    """Personal connection metadata; credentials are deliberately not serializable."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_source_organization_id: UUID | None
    catalog_key: str | None
    account_email: str | None
    granted_scopes: list[str] | None
    last_status: str | None
    authorization_generation: UUID
    is_enabled: bool
    created_at: datetime
    updated_at: datetime | None


class PrivateTaskBoardExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    table_id: UUID
    column_ids: dict[str, str]
    status_ids: dict[str, str]


class PrivateTaskRecordExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    table_id: UUID
    schema_version: int
    values: dict[str, JsonValue]
    revision: int
    created_at: datetime
    updated_at: datetime | None


class PrivateTaskHistoryExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    table_id: UUID
    record_id: UUID
    revision: int
    operation: str
    before: dict[str, JsonValue] | None
    after: dict[str, JsonValue] | None
    created_at: datetime


class PrivateTaskSchemaExport(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    table_id: UUID
    version: int
    columns: list[dict[str, JsonValue]]


class PersonalDataExport(BaseModel):
    """Everything this deployment holds about one person, as one document.

    A list per table rather than one flat stream, because a reader asking "what
    do you know about me" is asking a question per kind: which threads, which
    opinions, which devices, what an agent wrote down. Each list carries the
    fields named in `PersonalDataService` and no others - adding a column to a
    table must not silently add it to what every person can download.

    **The audit trail is deliberately absent.** An entry naming the person as an
    actor is the organization's record of what was done in it, not the person's
    data to take away - and an entry with its actor removed is worse than one
    naming a deleted account. `docs/security.md` says so in the same breath as
    the inventory.
    """

    private_task_history: list[PrivateTaskHistoryExport] = Field(default_factory=list)
    private_task_schemas: list[PrivateTaskSchemaExport] = Field(default_factory=list)
    private_task_boards: list[PrivateTaskBoardExport] = Field(default_factory=list)
    private_task_records: list[PrivateTaskRecordExport] = Field(default_factory=list)
    connected_accounts: list[ConnectedAccountExport] = Field(default_factory=list)
    coding_task_changes: list[CodingTaskChangeExport] = Field(default_factory=list)
    outcomes: list[OutcomeExport] = Field(default_factory=list)
    phone_contacts: list[PhoneContactExport] = Field(default_factory=list)
    phone_case_attempts: list[PhoneCaseAttemptExport] = Field(default_factory=list)
    phone_calls: list[PhoneCallExport] = Field(default_factory=list)
    project_trackers: list[ProjectTrackingExport] = Field(default_factory=list)
    routine_sources: list[RoutineSourceExport] = Field(default_factory=list)
    routine_health: list[RoutineHealthExport] = Field(default_factory=list)
    routine_device_waits: list[RoutineDeviceWaitExport] = Field(
        default_factory=list,
        description="Their durable device activations, including unconsumed event context.",
    )
    routine_deliveries: list[RoutineAnswerExport] = Field(
        default_factory=list,
        description="The person's canonical resumed routine answers and their console handoff status.",
    )
    exported_at: datetime = Field(description="When this document was produced.")
    profile: dict[str, Any] = Field(description="The account itself. Never the password hash.")
    conversations: list[dict[str, Any]] = Field(description="Threads this person started.")
    messages: list[dict[str, Any]] = Field(
        description=(
            "Every turn of those threads, answers included - a transcript with every "
            "second turn removed answers nothing."
        )
    )
    tool_calls: list[dict[str, Any]] = Field(
        description=(
            "What the agents did to answer those turns, with the arguments sent and "
            "what came back - a transcript without them says an agent did something "
            "and not what."
        )
    )
    memberships: list[dict[str, Any]] = Field(
        description="Which organizations they belong to, as what, and since when."
    )
    ratings: list[dict[str, Any]] = Field(description="Answers they marked good or bad.")
    case_verdicts: list[dict[str, Any]] = Field(
        description="Eval scores they passed or failed by hand, with the note they left."
    )
    scored_answers: list[dict[str, Any]] = Field(
        description="Answers to their runs that an eval score kept, with when it was scored."
    )
    sessions: list[dict[str, Any]] = Field(
        description="Where and when they signed in. Never the credential; the row holds a hash."
    )
    runs: list[dict[str, Any]] = Field(description="Runs they started, and what each cost.")
    knowledge_searches: list[dict[str, Any]] = Field(
        description="What agents searched their knowledge bases for while answering them."
    )
    memory: list[dict[str, Any]] = Field(
        description="What agents have written down about them, in every organization."
    )
    memory_claims: list[dict[str, Any]] = Field(
        description=(
            "The facts, preferences and decisions agents recorded about them, with their "
            "source, validity and status - the superseded, merged and retracted ones too."
        )
    )
    channel_identities: list[dict[str, Any]] = Field(
        description="The Slack, Telegram and Mattermost accounts they linked."
    )
    slash_commands: list[dict[str, Any]] = Field(description="Shortcuts they saved.")
    dashboard_layouts: list[dict[str, Any]] = Field(description="How they arranged their console.")
    notifications: list[dict[str, Any]] = Field(
        description=(
            "Every notification addressed to them, the ones a channel opt-out hid "
            "included - a row hidden from the bell is still a row held about them."
        )
    )
    notification_preferences: list[dict[str, Any]] = Field(
        description="Which events they chose to hear about, per channel."
    )
    notification_routes: list[dict[str, Any]] = Field(
        default_factory=list, description="Their explicit private notification destinations."
    )
    coding_accounts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Personal coding account metadata; never credentials or refresh tokens.",
    )
    browser_sign_ins: list[dict[str, Any]] = Field(
        description=(
            "The sites they kept a browser sign-in to, and when it was last used. "
            "Never the sign-in itself, which is their session on that site."
        )
    )
    api_keys: list[dict[str, Any]] = Field(
        description=(
            "The API keys they issued: name, prefix, permissions and dates. "
            "Never the key or its hash."
        )
    )
    suggestions: list[dict[str, Any]] = Field(
        description=(
            "What the platform proposed to them on its own initiative - drawn from "
            "their requests - and what they answered, dismissed ones included. "
            "What a watch found is among them, as kind `finding`."
        ),
    )
    watches: list[dict[str, Any]] = Field(
        description=(
            "What they asked the platform to watch in their own connections: what "
            "to look for and leave out, how often, and when it last looked."
        ),
    )
    oauth_grants: list[dict[str, Any]] = Field(
        description=(
            "The clients they let act as them, with the permissions and dates. "
            "Never a code or token the consent was exchanged for."
        )
    )
    case_proposals: list[dict[str, Any]] = Field(
        description=(
            "Test cases drafted from their conversations and still waiting for a "
            "decision - a paraphrase of what they asked is still about them."
        )
    )


class PersonalDataPurge(BaseModel):
    """What a deletion removed that no cascade would have reached."""

    memory_notes: int = Field(description="Notes agents held about them, across organizations.")
    channel_identities: int = Field(
        description="Platform accounts removed rather than left unlinked."
    )
    workspaces: int = Field(
        description="User-scoped agent workspaces, which no cascade reaches either."
    )
    dataset_cases: int = Field(
        description="Dataset cases taken from their conversations, kept but unlinked from them."
    )
    anonymised_cases: int = Field(
        description="Dataset case revisions whose text, taken from them, was replaced."
    )
    case_copies: int = Field(
        description="Eval attempts and scores of those revisions, cleared of what they recorded."
    )
    history_turns: int = Field(
        description="Cases asked by somebody else whose earlier turns held theirs, now replaced."
    )
    case_notes: int = Field(
        description="Dataset cases that kept their comment on somebody else's answer as a note."
    )
    evidence_quotes: int = Field(
        description="Quotes of them the authoring assistant kept as evidence, removed."
    )
    gap_drafts: int = Field(
        description="Knowledge-gap drafts written from topics holding their searches, discarded."
    )
    knowledge_searches: int = Field(
        description="Knowledge searches made while answering them, including API runs."
    )
    knowledge_gap_reasons: int = Field(
        default=0, description="Classifier reasons about answers to this person, cleared."
    )
    scored_answers: int = Field(
        description="Eval scores of their runs, kept but without the answer they scored."
    )
    case_proposals: int = Field(
        description="Proposed dataset cases drafted from their conversations, deleted undecided.",
    )
