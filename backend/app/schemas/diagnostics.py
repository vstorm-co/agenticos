"""Version-one diagnostic protocol: closed fields and bounded cardinality."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

type Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
type EventId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
type Surface = Literal["web", "desktop", "mobile"]
type Feature = Literal[
    "chat",
    "desktop",
    "mobile",
    "channels",
    "workflows",
    "rag",
    "voice",
    "routines",
    "projects",
    "skills",
]
type Bucket = Literal["0", "1-9", "10-99", "100-999", "1000+"]
type Component = Literal[
    "api", "worker", "agents", "rag", "channels", "voice", "frontend", "desktop", "mobile"
]
type ErrorCode = Literal[
    "internal_error", "run_failed", "job_failed", "ingestion_failed", "connection_failed"
]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Event(ProtocolModel):
    protocol: Literal[1] = 1
    instance_id: Digest
    event_id: EventId
    at: Annotated[StrictInt, Field(ge=0)]


class Registration(Event):
    kind: Literal["registration"] = "registration"
    public_key: Annotated[str, Field(min_length=44, max_length=44)]


class Health(ProtocolModel):
    component: Literal["database", "redis", "worker"]
    status: Literal["healthy", "degraded", "unknown"]


class FeatureUsage(ProtocolModel):
    name: Feature
    enabled: bool
    usage: Bucket = "0"


class Heartbeat(Event):
    kind: Literal["heartbeat"] = "heartbeat"
    version: Annotated[
        str, Field(pattern=r"^\d{1,4}\.\d{1,4}\.\d{1,4}(?:[-+][a-zA-Z0-9.-]{1,40})?$")
    ]
    health: Annotated[list[Health], Field(max_length=3)] = Field(default_factory=list)
    features: Annotated[list[FeatureUsage], Field(max_length=10)] = Field(default_factory=list)


class ErrorEvent(Event):
    kind: Literal["error"] = "error"
    component: Component
    code: ErrorCode
    fingerprint: Digest
    count: Annotated[StrictInt, Field(ge=1, le=1000)] = 1


class Presence(Event):
    kind: Literal["presence"] = "presence"
    user_id: Digest
    surface: Surface
    expires_at: StrictInt


class SignedRegistration(ProtocolModel):
    payload: Registration
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class SignedHeartbeat(ProtocolModel):
    payload: Heartbeat
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class SignedError(ProtocolModel):
    payload: ErrorEvent
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class SignedPresence(ProtocolModel):
    payload: Presence
    signature: Annotated[str, Field(min_length=88, max_length=88)]


class PresenceCreate(ProtocolModel):
    surface: Surface


class PresenceRead(ProtocolModel):
    endpoint: str
    event: SignedPresence


class DiagnosticsStatusRead(ProtocolModel):
    enabled: bool
    collector: str
    instance_id: str | None
    last_attempt: int | None
    last_success: int | None
    last_error: Literal["transport", "rejected"] | None
