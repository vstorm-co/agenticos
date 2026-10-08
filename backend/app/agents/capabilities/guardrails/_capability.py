"""Input, output and tool-result guardrails - a check that can stop a run.

The edges, the detectors and the guard vocabulary all come from
`pydantic-ai-harness`; what this module adds is the two things a platform has to
add to a library that expects hand-written Python guards.

**Config, not callables.** An agent here is *data* - a spec with a config blob,
never code - so a client cannot hand us a `guard=my_function`. The config selects
and parameterises the ready-made detectors instead: three toggles and a keyword
list per edge, assembled into one detector chain per edge by :func:`_edge_detector`.

**A block is an outcome, not a graceful answer.** The harness makes a `block`
verdict graceful - an input block substitutes a refusal response and the run
*completes* with it as the answer, a tool block replaces the result and the model
carries on. For governance that is exactly wrong: a refusal should be a visible run
outcome an operator can filter for, not a completed answer that reads like any
other. So the detector chain *raises* :class:`GuardrailBlocked` on a block instead
of returning one, and the runner maps that to `RunStatus.GUARDRAIL_BLOCKED` the way
it maps `BudgetExceeded`. Redaction (`replace`) keeps its harness semantics: a
detector that scrubs a key and lets the run finish is the whole point.

The raise escapes `agent.run()` cleanly from every edge - `wrap_model_request`
(input), `after_output_process` (output) and `after_tool_execute` (tool result) all
propagate a guard's exception rather than converting it, which is what makes one
`GuardrailBlocked` type serve all three.

**The output edge also screens the stream.** The harness's `OutputGuardrail` reads
the finished answer, and every surface here streams it first - the web chat sends
each delta to the socket and a channel bot edits its reply as the text arrives - so
a redacted key was on screen, and in the stored turn, before the redaction ran
(agenticos#1900). :class:`ScreenedStream` holds each text and reasoning part back
from whoever consumes the stream until the part is complete, and releases it
through the same detector the output guardrail runs.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass, replace

from pydantic import BaseModel, Field
from pydantic_ai.capabilities import AbstractCapability, CombinedCapability
from pydantic_ai.messages import (
    AgentStreamEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)
from pydantic_ai.tools import RunContext
from pydantic_ai_harness.guardrails import (
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
    ToolGuardrail,
)
from pydantic_ai_harness.guardrails.detectors import (
    blocked_keywords,
    for_text,
    for_tool_result_text,
    redact_personal_data,
    redact_secrets,
)

logger = logging.getLogger(__name__)

TextDetector = Callable[[str], GuardrailResult]
"""A detector reads text and returns a verdict. The harness's own signature."""

_KEYWORD_SPLIT = re.compile(r"[,\n]")

WITHHELD_REASONING = "[reasoning withheld by the output guardrail]"
"""What a reasoning part the output check refused shows in its place."""
"""Blocked keywords arrive as one string, comma- or newline-separated.

A string rather than a `list[str]` because the Builder's generated form renders
only scalar and enum fields - a list arrives as a text box either way, so it is
one honestly rather than a control that looks structured and is not.
"""

_BLOCK_MESSAGE = {
    "input": "This request was blocked by an input guardrail.",
    "output": "This response was blocked by an output guardrail.",
    "tool_result": "A tool result was blocked by a guardrail.",
}
"""What the run row records on a block. Names the edge and the refusal, never the
content that tripped it - the row is read by every member who can see the run, and
the matched term (an org's own configured keyword) belongs in the log beside it."""


class GuardrailBlocked(Exception):
    """A guardrail refused a run at one of its edges.

    A plain `Exception`, not an `AppException`, for the reason `BudgetExceeded` is:
    the runner catches it and maps it to its own `RunStatus`, and a trip is the
    platform working rather than a malfunction. The message is safe to store on the
    run - it names the edge and the refusal, never the offending text.
    """

    def __init__(self, *, edge: str, message: str) -> None:
        self.edge = edge
        super().__init__(message)


class GuardrailsConfig(BaseModel):
    """Which checks run on which edge.

    Flat booleans and one delimited string per edge, so the Builder can render the
    whole form. Every field defaults off: an agent that enables the capability but
    configures no edge gets no guardrail at all, and the builder returns `None`.

    The three edges are the three the harness's text detectors have adapters for -
    the prompt (a `str`), the output (via `for_text`) and a tool result (via
    `for_tool_result_text`). Tool *arguments* are a structured mapping with no text
    adapter, so they are not an edge here.
    """

    redact_secrets_in: bool = Field(
        default=False, description="Redact API keys and tokens from the user's prompt"
    )
    redact_pii_in: bool = Field(
        default=False, description="Redact emails, IBANs, cards and SSNs from the prompt"
    )
    blocked_keywords_in: str = Field(
        default="",
        description="Block the run if the prompt contains any of these terms (comma or newline separated)",
    )
    redact_secrets_out: bool = Field(
        default=False, description="Redact API keys and tokens from the agent's answer"
    )
    redact_pii_out: bool = Field(
        default=False, description="Redact emails, IBANs, cards and SSNs from the answer"
    )
    blocked_keywords_out: str = Field(
        default="",
        description="Block the run if the answer contains any of these terms (comma or newline separated)",
    )
    redact_secrets_tool: bool = Field(
        default=False,
        description="Redact API keys and tokens from tool results before the model reads them",
    )
    redact_pii_tool: bool = Field(
        default=False, description="Redact emails, IBANs, cards and SSNs from tool results"
    )
    blocked_keywords_tool: str = Field(
        default="",
        description="Block the run if a tool result contains any of these terms (comma or newline separated)",
    )


def _keywords(raw: str) -> list[str]:
    """The terms in a delimited keyword string, blanks dropped."""
    return [term.strip() for term in _KEYWORD_SPLIT.split(raw) if term.strip()]


def _edge_detector(
    *, redact_secrets_on: bool, redact_pii_on: bool, keywords: list[str], edge: str
) -> TextDetector | None:
    """One text detector for an edge: redact first, then block.

    Redactors run in order and thread their cleaned text forward, so a key scrubbed
    by the first is invisible to the keyword check after it. The keyword check runs
    last, on already-redacted text, and *raises* :class:`GuardrailBlocked` rather
    than returning a `block` verdict - that is what turns a block into a run outcome
    instead of a graceful answer.

    Returns `None` when nothing is configured for the edge, so the caller attaches
    no guardrail there rather than an inert one.
    """
    redactors: list[TextDetector] = []
    if redact_secrets_on:
        redactors.append(redact_secrets)
    if redact_pii_on:
        redactors.append(redact_personal_data)
    keyword_detector = blocked_keywords(keywords) if keywords else None
    if not redactors and keyword_detector is None:
        return None

    def detect(text: str) -> GuardrailResult:
        cleaned = text
        replaced = False
        for redactor in redactors:
            verdict = redactor(cleaned)
            if verdict.action == "replace":
                # A redactor's replacement is always the cleaned string.
                cleaned = str(verdict.replacement)
                replaced = True
        if keyword_detector is not None and keyword_detector(cleaned).action == "block":
            logger.info("Guardrail blocked a run at the %s edge", edge)
            raise GuardrailBlocked(edge=edge, message=_BLOCK_MESSAGE[edge])
        return GuardrailResult.replace(cleaned) if replaced else GuardrailResult.allow()

    return detect


@dataclass
class ScreenedStream(AbstractCapability[object]):
    """Release the answer to a streaming consumer only once the output check has read it.

    Text and reasoning parts are held back whole: their start and delta events are
    dropped, and when a part ends it is released as one start event carrying the
    screened content, followed by its end event carrying the same. Screening a
    complete part is what makes this safe - a key split across two deltas is
    whole by the time the detector reads it - and it covers text the harness
    guardrail never reads at all: what the model writes before calling a tool is
    not the run's output, but a streaming surface shows it and stores it.

    A blocked keyword in a text part raises :class:`GuardrailBlocked` out of the
    stream before any of that part has been released, so the run ends as
    `GUARDRAIL_BLOCKED` with none of the blocked text shown or written down. A
    refused reasoning part is replaced by `WITHHELD_REASONING` instead: reasoning
    routinely restates the question, and ending a run whose answer is clean over
    a word the model only thought would refuse ordinary questions.

    The cost falls only on an agent that configured an output check: its answer
    arrives a part at a time rather than token by token. The run's own messages
    and output are untouched - the library applies this hook to the consumer's
    view only - so the final answer is still redacted by the output guardrail.
    """

    screen: TextDetector

    async def wrap_run_event_stream(
        self,
        ctx: RunContext[object],
        *,
        stream: AsyncIterable[AgentStreamEvent],
    ) -> AsyncIterable[AgentStreamEvent]:
        """Drop text and reasoning as they stream, and release each part screened."""
        # The start events held back, by part index: released with the screened
        # part so `previous_part_kind` survives.
        held: dict[int, PartStartEvent] = {}
        async for event in stream:
            match event:
                case PartStartEvent(part=TextPart() | ThinkingPart()):
                    held[event.index] = event
                case PartDeltaEvent(delta=TextPartDelta() | ThinkingPartDelta()):
                    pass
                case PartEndEvent(part=TextPart() | ThinkingPart() as part):
                    screened = replace(part, content=self._screened(part))
                    yield replace(held.pop(event.index), part=screened)
                    yield replace(event, part=screened)
                case _:
                    yield event

    def _screened(self, part: TextPart | ThinkingPart) -> str:
        """The part's content as a consumer may see it; a blocked text part raises."""
        try:
            verdict = self.screen(part.content)
        except GuardrailBlocked:
            if isinstance(part, TextPart):
                raise
            return WITHHELD_REASONING
        # A detector here only allows or replaces; a block has raised.
        return str(verdict.replacement) if verdict.action == "replace" else part.content


def build_guardrails(config: GuardrailsConfig) -> CombinedCapability[object] | None:
    """The harness capabilities this configuration asks for, combined into one.

    One capability per configured edge, wrapped in a `CombinedCapability` so a
    single binding attaches all of them. The output edge brings a second,
    :class:`ScreenedStream`, sharing its detector: the guardrail screens the answer
    the run ends with and the stream screen what a surface shows while it is
    written, and neither is safe without the other. `None` when no edge is configured - the
    "enabled but inert" state does not exist, which is the "pays nothing when
    absent" contract every capability owes.
    """
    edges: list[AbstractCapability[object]] = []

    input_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_in,
        redact_pii_on=config.redact_pii_in,
        keywords=_keywords(config.blocked_keywords_in),
        edge="input",
    )
    if input_detector is not None:
        edges.append(InputGuardrail(guard=input_detector))

    output_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_out,
        redact_pii_on=config.redact_pii_out,
        keywords=_keywords(config.blocked_keywords_out),
        edge="output",
    )
    if output_detector is not None:
        edges.append(OutputGuardrail(guard=for_text(output_detector, on_other="allow")))
        edges.append(ScreenedStream(screen=output_detector))

    tool_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_tool,
        redact_pii_on=config.redact_pii_tool,
        keywords=_keywords(config.blocked_keywords_tool),
        edge="tool_result",
    )
    if tool_detector is not None:
        edges.append(
            ToolGuardrail(result_guard=for_tool_result_text(tool_detector, on_other="allow"))
        )

    if not edges:
        return None
    return CombinedCapability(capabilities=edges)
