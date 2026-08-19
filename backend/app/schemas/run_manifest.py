"""What a run handed its model, on the way out.

Every field defaults to its empty answer, and that is deliberate rather than
lax. The payload is stored as it was recorded, so a row written by an older
build carries whatever that build knew how to record - and a schema that
*required* a field added later would refuse to validate exactly the old runs
somebody is looking back at, which in FastAPI is a 500 on the whole response
rather than a gap in one panel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ManifestTool(BaseSchema):
    """One tool as the provider was told about it.

    Attributes:
        name: What the model calls it, after any per-agent renaming.
        description: The sentence the model decides on. Nowhere else readable,
            and the usual explanation for a tool an agent never calls.
        parameters_json_schema: The argument schema, verbatim.
        kind: `function`, or `output` for the tool carrying a structured answer.
    """

    name: str
    description: str | None = None
    parameters_json_schema: dict[str, Any] = Field(default_factory=dict)
    kind: str = "function"


class ManifestRequest(BaseSchema):
    """One model request the run made, and what it cost in time.

    A run is one row with one duration, and forty seconds is either one slow
    request or nine quick ones with eight tool calls between them - opposite
    problems the run row cannot tell apart.

    Attributes:
        failed: The exception class, where the request raised. Never its message:
            a provider SDK puts the failing URL, and therefore a key, in that
            string.
    """

    index: int
    started_at: datetime | None = None
    duration_ms: int = 0
    model: str | None = None
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    finish_reason: str | None = None
    failed: str | None = None


class RunManifestRead(BaseSchema):
    """The whole record, as `GET /runs/{run_id}/manifest` answers it.

    Attributes:
        instructions: The system prompt as composed and sent - the spec's text
            plus the platform's, a channel binding's, the bound skills' and
            whatever else the builder added. What the model was told, rather than
            what the spec says.
        system_prompts: Anything sent as a system part, which is separate from
            the instructions on the wire.
        tools: Every tool the provider was told about, in the order it was told.
        settings: Temperature and its neighbours, as sent. Provider passthrough -
            `extra_headers`, `extra_body` - is never recorded: it is where a
            credential rides.
        requests: One entry per model request, in order. The waterfall.
        messages: The last request's messages, dumped - the whole of what the
            model saw at the end of the run, retries and tool returns included.
        truncated: Whether the record was trimmed to fit its size ceiling. A
            reader must be able to tell a run that sent little from a record that
            was cut.
    """

    run_id: UUID
    recorded_at: datetime
    instructions: str | None = None
    system_prompts: list[str] = Field(default_factory=list)
    tools: list[ManifestTool] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    requests: list[ManifestRequest] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
