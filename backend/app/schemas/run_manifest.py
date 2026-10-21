"""What a run handed its model, on the way out.

Every field defaults to its empty answer, and that is deliberate rather than
lax. The payload is stored as it was recorded, so a row written by an older
build carries whatever that build knew how to record - and a schema that
*required* a field added later would refuse to validate exactly the old runs
somebody is looking back at, which in FastAPI is a 500 on the whole response
rather than a gap in one panel.
"""

from datetime import datetime
from typing import Any, Literal
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
    cache_write_tokens: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    finish_reason: str | None = None
    failed: str | None = None
    cache: Literal["bust", "expired"] | None = Field(
        default=None,
        description=(
            "`bust` when this request's cached prompt prefix collapsed while the provider "
            "should still have held it - the prefix moved; `expired` when its retention "
            "window had passed. Null when the cache held, or was not in play"
        ),
    )
    cache_missed_tokens: int = Field(
        default=0,
        description=(
            "Of the prefix earlier requests cached, how many tokens this request did not "
            "read back. A miss, not a bill: a compaction that shrank the request misses "
            "tokens it never sent again"
        ),
    )


class ManifestReview(BaseSchema):
    """One correction a run reviewer sent while the run went (#2106).

    Attributes:
        reviewer: The reviewer's name, as the spec gives it - what the run's model
            was told the correction came from.
        after_request: The model request the review read up to.
        steer: The correction, as the run's model received it.
    """

    reviewer: str
    after_request: int
    steer: str


class ManifestCodeCall(BaseSchema):
    """One tool call a `run_code` script made.

    Attributes:
        tool: The tool it called.
        args: Its arguments, as JSON, cut to a preview.
        status: `returned`, or `failed` when the call raised or never finished.
    """

    tool: str
    args: str
    status: Literal["returned", "failed"]


class ManifestCodeRun(BaseSchema):
    """One script code mode ran, and the calls it made (#2107).

    Attributes:
        tool_call_id: The `run_code` call it was, in the transcript.
        code: The script, as the model wrote it.
        calls: The tool calls the script made, in the order they started - the
            first hundred.
        omitted_calls: How many more it made beyond those listed.
    """

    tool_call_id: str
    code: str
    calls: list[ManifestCodeCall] = Field(default_factory=list)
    omitted_calls: int = 0


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
    reviews: list[ManifestReview] = Field(default_factory=list)
    code_runs: list[ManifestCodeRun] = Field(default_factory=list)
    truncated: bool = False
