"""The Agent2Agent (A2A) protocol, as far as this platform speaks it (#2092).

A2A 0.3 over JSON-RPC: an **agent card** says what an agent is and where to send
work, and `message/send` hands it a message and gets back a **task** - its state,
and the artifacts it produced. These models are the wire shapes both directions
use: the server half answers other systems' clients with them, and the client half
reads other vendors' agents through them.

Only what is used is modelled. Unknown fields are kept rather than refused
(`extra="allow"`), because another vendor's card or task carries extensions this
platform has no reason to reject.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROTOCOL_VERSION = "0.3.0"

ENDPOINT_MAX_LENGTH = 1000
"""The longest endpoint a card may advertise: what `external_agents.endpoint_url` holds."""

TaskState = Literal[
    "submitted",
    "working",
    "input-required",
    "completed",
    "canceled",
    "failed",
    "rejected",
    "auth-required",
    "unknown",
]
"""Where a task stands. `input-required` is how a run parked for a person reads."""


class _Wire(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TextPart(_Wire):
    kind: Literal["text"] = "text"
    text: str


class Part(_Wire):
    """Any part. Only text is read; a file or data part arrives and is described."""

    kind: str
    text: str | None = None


class Message(_Wire):
    role: Literal["user", "agent"]
    parts: list[Part]
    message_id: str = Field(alias="messageId")
    context_id: str | None = Field(default=None, alias="contextId")
    task_id: str | None = Field(default=None, alias="taskId")
    kind: Literal["message"] = "message"

    def text(self) -> str:
        """Every text part, joined - what a run is asked or what an agent answered."""
        return "\n\n".join(part.text for part in self.parts if part.text)


class TaskStatus(_Wire):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None


class Artifact(_Wire):
    artifact_id: str = Field(alias="artifactId")
    name: str | None = None
    parts: list[Part]


class Task(_Wire):
    id: str
    context_id: str = Field(alias="contextId")
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    kind: Literal["task"] = "task"

    def text(self) -> str:
        """The answer: the artifacts' text, or the status message's where there is none."""
        found = "\n\n".join(
            part.text for artifact in self.artifacts for part in artifact.parts if part.text
        )
        if found:
            return found
        return self.status.message.text() if self.status.message is not None else ""


class AgentSkill(_Wire):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class AgentCapabilities(_Wire):
    streaming: bool = False
    push_notifications: bool = Field(default=False, alias="pushNotifications")


class AgentCard(_Wire):
    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    name: str
    description: str = ""
    url: str = Field(max_length=ENDPOINT_MAX_LENGTH)
    preferred_transport: str = Field(default="JSONRPC", alias="preferredTransport")
    version: str = "1"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    default_input_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"], alias="defaultInputModes"
    )
    default_output_modes: list[str] = Field(
        default_factory=lambda: ["text/plain"], alias="defaultOutputModes"
    )
    skills: list[AgentSkill] = Field(default_factory=list)
    security_schemes: dict[str, dict[str, Any]] = Field(
        default_factory=dict, alias="securitySchemes"
    )
    security: list[dict[str, list[str]]] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def _an_http_endpoint(cls, url: str) -> str:
        """Where the work is sent, so an address it can be sent to.

        Refused when the card is read, not when the first delegation fails: an
        agent registered with an endpoint nothing can reach publishes, and
        every task handed to it fails afterwards.
        """
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("An agent card's url must be an http or https address")
        # Stored and shown as configuration, so it carries no credential: a key is
        # the vault's, sent as the bearer token.
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("An agent card's url must not carry a user name or password")
        return url


class JsonRpcRequest(_Wire):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcError(_Wire):
    code: int
    message: str
    data: dict[str, Any] | None = None


# JSON-RPC's own codes, and the ones A2A adds.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
UNSUPPORTED_OPERATION = -32004
