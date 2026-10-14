"""Voice conversations on the wire (#54): readiness, socket frames, usage."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class VoiceReadinessRead(BaseSchema):
    available: bool
    unavailable: (
        Literal["org_off", "not_in_chat", "no_voice", "not_offered", "no_key", "minutes_exhausted"]
        | None
    ) = None
    transport: Literal["webrtc", "relay"] | None = None
    provider: str | None = None
    model: str | None = None
    cap_seconds: int = Field(description="The longest this call could run, after the minutes left")
    minutes_left: int | None = Field(
        default=None, description="This month's remaining call minutes; null = budgets only"
    )
    unavailable_capabilities: list[str] = Field(default_factory=list)


class StartFrame(BaseSchema):
    """The first frame on the voice socket: which agent, which conversation, the SDP offer."""

    type: Literal["start"]
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    sdp_offer: str | None = Field(default=None, max_length=20_000)
    resume_of: UUID | None = Field(
        default=None, description="The call this connection continues after a drop, within 10 s"
    )


class ApprovalFrame(BaseSchema):
    """The person on the call deciding an approval the call is waiting on."""

    type: Literal["approval"]
    id: str
    decision: Literal["approve", "deny"]


class PttFrame(BaseSchema):
    """Push-to-talk held down or let go."""

    type: Literal["ptt"]
    state: Literal["down", "up"]


class MuteFrame(BaseSchema):
    """The caller's microphone muted or unmuted."""

    type: Literal["mute"]
    muted: bool


class EndFrame(BaseSchema):
    """The caller hanging up."""

    type: Literal["end"]


class PlayedFrame(BaseSchema):
    """How many bytes of the agent's audio the browser has played (the relay)."""

    type: Literal["played"]
    bytes: int = Field(ge=0)


ClientFrame = Annotated[
    StartFrame | ApprovalFrame | PttFrame | MuteFrame | EndFrame | PlayedFrame,
    Field(discriminator="type"),
]


class AnswerFrame(BaseSchema):
    """The provider's SDP answer, for the browser's peer connection (WebRTC)."""

    type: Literal["answer"]
    sdp: str


class ReadyFrame(BaseSchema):
    """The call is set up: its ids, its transport and its limits."""

    type: Literal["ready"]
    call_id: UUID
    run_id: UUID
    conversation_id: UUID
    transport: Literal["webrtc", "relay"]
    input_sample_rate: int
    output_sample_rate: int
    cap_seconds: int
    minutes_left: int | None = None


class StateFrame(BaseSchema):
    """Who is talking, or what the agent is doing."""

    type: Literal["state"]
    state: Literal[
        "connecting",
        "listening",
        "user_speaking",
        "thinking",
        "agent_speaking",
        "interrupted",
        "tool_running",
        "awaiting_approval",
    ]


class CaptionFrame(BaseSchema):
    """One speech part's caption, as it is spoken.

    `turn_id` is the `turn_id` of the message the part is saved in
    (`<call id>:<n>:<role>`), so a `turn_saved` frame replaces every caption
    carrying it. One caller utterance is one turn; all of the agent's parts in
    one response are one turn, told apart by `part`. Exactly one of the text
    fields is set: `delta` appends words, `text` replaces the part's caption with
    the screened text so far (an agent with an output guardrail, whose captions
    arrive a sentence at a time), and `final` replaces it with the finished,
    screened part.
    """

    model_config = BaseSchema.model_config | {"str_strip_whitespace": False}

    type: Literal["caption"]
    role: Literal["user", "assistant"]
    turn_id: str
    part: int
    delta: str | None = None
    text: str | None = None
    final: str | None = None


class ToolFrame(BaseSchema):
    """A tool the agent is running, or has finished."""

    type: Literal["tool"]
    name: str
    status: Literal["running", "done"]


class TurnSavedFrame(BaseSchema):
    """A finished turn, as the message it was saved as; it replaces its caption."""

    type: Literal["turn_saved"]
    message: dict[str, object]


class ApprovalRequiredFrame(BaseSchema):
    """A tool call waiting on the person on the call: its exact arguments and what they said."""

    type: Literal["approval_required"]
    id: str
    tool: str
    args: dict[str, object]
    said: str | None = None
    timeout_seconds: int


class ApprovalUnavailableFrame(BaseSchema):
    """A tool call this caller cannot approve by voice."""

    type: Literal["approval_unavailable"]
    tool: str
    args: dict[str, object]


class ApprovalSettledFrame(BaseSchema):
    """How an approval the call was waiting on ended."""

    type: Literal["approval_settled"]
    id: str
    outcome: Literal["approved", "denied", "expired"]


class NoticeFrame(BaseSchema):
    """Something the call view says in words: a guardrail hit, a provider error, a limit."""

    type: Literal["notice"]
    kind: str
    message: str | None = None


class LimitFrame(BaseSchema):
    """The call's time is nearly up."""

    type: Literal["limit"]
    seconds_left: int


class EndedFrame(BaseSchema):
    """The call is over, and why."""

    type: Literal["ended"]
    reason: str
    message: str | None = None


class ClearPlaybackFrame(BaseSchema):
    """The relay: drop the agent's queued audio, the caller talked over it."""

    type: Literal["clear_playback"]


ServerFrame = Annotated[
    AnswerFrame
    | ReadyFrame
    | StateFrame
    | CaptionFrame
    | ToolFrame
    | TurnSavedFrame
    | ApprovalRequiredFrame
    | ApprovalUnavailableFrame
    | ApprovalSettledFrame
    | NoticeFrame
    | LimitFrame
    | EndedFrame
    | ClearPlaybackFrame,
    Field(discriminator="type"),
]
"""Every JSON frame the server sends on the voice socket: the contract the call view reads."""
