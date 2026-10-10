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
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_ai.capabilities import AbstractCapability, CombinedCapability
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)
from pydantic_ai.models import ModelRequestContext
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

from app.core.phone import (
    DEFAULT_PHONE_REGIONS,
    MAX_PHONE_REGIONS,
    MAX_PHONE_REGIONS_CHARS,
    parse_phone_regions,
    phone_text_error,
    redact_phone_numbers,
)

logger = logging.getLogger(__name__)

TextDetector = Callable[[str], GuardrailResult]
"""A detector reads text and returns a verdict. The harness's own signature."""

_KEYWORD_SPLIT = re.compile(r"[,\n]")
"""Blocked keywords arrive as one string, comma- or newline-separated.

A string rather than a `list[str]` because the Builder's generated form renders
only scalar and enum fields - a list arrives as a text box either way, so it is
one honestly rather than a control that looks structured and is not.
"""

WITHHELD_REASONING = "[reasoning withheld by the output guardrail]"
"""What a reasoning part the output check refused shows in its place."""

_BOUNDARY_CHARS = 1_000
"""How much of the text already released is screened again with the next part, at least.

A key or a blocked keyword split across two parts - text written before a tool
call and text after it - is harmless in each. Screened with the tail of what came
before, the part that completes it is redacted or blocked. Far longer than any
value the detectors match, and short enough to add little to each screen.
"""

_BLOCK_MESSAGE = {
    "input": "This request was blocked by an input guardrail.",
    "output": "This response was blocked by an output guardrail.",
    "tool_result": "A tool result was blocked by a guardrail.",
    "tool_args": "A tool call was blocked by a guardrail.",
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
    whole form. Every edge field defaults off: an agent that enables the capability
    but configures no edge gets no guardrail at all, and the builder returns `None`.
    `phone_regions` is the one field with a value by default, and it only changes
    what a PII redaction reads.

    Three edges are the ones the harness's text detectors have adapters for - the
    prompt (a `str`), the output (via `for_text`) and a tool result (via
    `for_tool_result_text`). The fourth, tool *arguments*, is a structured mapping
    with no harness adapter, so :class:`ScreenedToolArgs` screens each string in it
    (agenticos#2000). An edge of its own rather than part of the output check: what
    an agent passes a tool is not its answer, and redacting it changes what the
    tool does - an e-mail sent with a placeholder where the key was.
    """

    redact_secrets_in: bool = Field(
        default=False, description="Redact API keys and tokens from the user's prompt"
    )
    redact_pii_in: bool = Field(
        default=False,
        description="Redact emails, phone numbers, IBANs, cards and SSNs from the prompt",
    )
    blocked_keywords_in: str = Field(
        default="",
        description="Block the run if the prompt contains any of these terms (comma or newline separated)",
    )
    redact_secrets_out: bool = Field(
        default=False, description="Redact API keys and tokens from the agent's answer"
    )
    redact_pii_out: bool = Field(
        default=False,
        description="Redact emails, phone numbers, IBANs, cards and SSNs from the answer",
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
        default=False,
        description="Redact emails, phone numbers, IBANs, cards and SSNs from tool results",
    )
    blocked_keywords_tool: str = Field(
        default="",
        description="Block the run if a tool result contains any of these terms (comma or newline separated)",
    )
    redact_secrets_args: bool = Field(
        default=False,
        description="Redact API keys and tokens from the arguments the agent passes a tool",
    )
    redact_pii_args: bool = Field(
        default=False,
        description="Redact emails, phone numbers, IBANs, cards and SSNs from tool arguments",
    )
    blocked_keywords_args: str = Field(
        default="",
        description="Block the run if a tool's arguments contain any of these terms (comma or newline separated)",
    )
    phone_regions: str = Field(
        default=DEFAULT_PHONE_REGIONS,
        description=(
            "Countries whose national phone formats PII redaction reads, as two-letter codes "
            f"(comma or newline separated), at most {MAX_PHONE_REGIONS} regions "
            f"and {MAX_PHONE_REGIONS_CHARS} characters. "
            "A number written with + is redacted whatever is listed"
        ),
        json_schema_extra={"x-advanced": True},
    )

    @field_validator("phone_regions")
    @classmethod
    def _known_regions(cls, raw: str) -> str:
        """Reject unknown regions at publish rather than on every agent run."""
        parse_phone_regions(raw)
        return raw


def _keywords(raw: str) -> list[str]:
    """The terms in a delimited keyword string, blanks dropped."""
    return [term.strip() for term in _KEYWORD_SPLIT.split(raw) if term.strip()]


def refuse_long_text(regions: tuple[str, ...]) -> TextDetector:
    """Check raw length before other redactors; check digits after they run."""

    def detect(text: str) -> GuardrailResult:
        error = phone_text_error(text, regions, check_digits=False)
        return GuardrailResult.block(error) if error else GuardrailResult.allow()

    return detect


def phone_numbers(regions: tuple[str, ...]) -> TextDetector:
    """Adapt phone matching and scan limits to the harness verdicts."""

    def detect(text: str) -> GuardrailResult:
        if error := phone_text_error(text, regions):
            return GuardrailResult.block(error)
        redacted, found = redact_phone_numbers(text, regions)
        return GuardrailResult.replace(redacted) if found else GuardrailResult.allow()

    return detect


def _edge_detector(
    *,
    redact_secrets_on: bool,
    redact_pii_on: bool,
    phone_regions: tuple[str, ...],
    keywords: list[str],
    edge: str,
) -> TextDetector | None:
    """One text detector for an edge: redact first, then block.

    Redactors run in order and thread their cleaned text forward, so a key scrubbed
    by the first is invisible to the keyword check after it. A redactor that returns
    `block` - the phone detector, for a text too long to read - ends the
    run there, as a keyword block does. The keyword check runs last, on
    already-redacted text, and *raises* :class:`GuardrailBlocked` rather than
    returning a `block` verdict - that is what turns a block into a run outcome
    instead of a graceful answer.

    Returns `None` when nothing is configured for the edge, so the caller attaches
    no guardrail there rather than an inert one.
    """
    redactors: list[TextDetector] = []
    if redact_pii_on:
        # The phone detector refuses a text this long, so it is refused before any
        # redactor scans it: the harness patterns alone took some 30 s on a prompt
        # the size of a request body.
        redactors.append(refuse_long_text(phone_regions))
    if redact_secrets_on:
        redactors.append(redact_secrets)
    if redact_pii_on:
        # After the harness patterns, so a card or an SSN is already a placeholder
        # and cannot be read as a national phone number.
        redactors.extend((redact_personal_data, phone_numbers(phone_regions)))
    keyword_detector = blocked_keywords(keywords) if keywords else None
    if not redactors and keyword_detector is None:
        return None

    def detect(text: str) -> GuardrailResult:
        cleaned = text
        replaced = False
        for redactor in redactors:
            verdict = redactor(cleaned)
            if verdict.action == "block":
                # A redactor that could not read the text. Passing it on would
                # pass on whatever it failed to redact.
                logger.info("A redactor refused text at the %s edge: %s", edge, verdict.message)
                raise GuardrailBlocked(
                    edge=edge, message=f"{_BLOCK_MESSAGE[edge]} {verdict.message}"
                )
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
    fits: Callable[[str], bool] | None = None
    """Whether a text is within the screen's size limit, when it has one.

    The phone detector refuses a text past its character or digit ceiling. The
    released tail is context, not the part, so it must not push a part that is
    within the ceiling past it: such a part is screened alone, and its boundary
    with the tail on a window of its own."""
    tail_chars: int = _BOUNDARY_CHARS
    """How much released text is kept to screen with the next part: at least
    `_BOUNDARY_CHARS`, and longer when a blocked keyword is, so a keyword split
    across two parts is never cut off at its start."""

    _released: str = field(default="", init=False, repr=False)
    """The raw tail of what this run has released, text and reasoning in order.

    One tail for both, because a surface shows and stores them in order, so a
    key begun in reasoning and finished in the answer is one key on screen. Held
    on the instance because the stream hook runs once per node, and a part that
    completes a value is usually in the response after the tool call."""

    async def for_run(self, ctx: RunContext[object]) -> ScreenedStream:
        """A fresh instance per run, so one run's released tail never meets another's."""
        return ScreenedStream(screen=self.screen, fits=self.fits, tail_chars=self.tail_chars)

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
                    before = self._released
                    content = self._screened(part, before)
                    # A withheld part is not shown, so nothing can complete it.
                    withheld = content is None
                    tail = "" if withheld else before + part.content
                    self._released = tail[-self.tail_chars :]
                    content = WITHHELD_REASONING if content is None else content
                    screened = replace(part, content=content)
                    yield replace(held.pop(event.index), part=screened)
                    yield replace(event, part=screened)
                case _:
                    yield event

    def _screened(self, part: TextPart | ThinkingPart, before: str) -> str | None:
        """The part's content as a consumer may see it, or `None` for a withheld
        reasoning part; a blocked text part raises.

        Screened after `before`, the raw tail already released, and released only
        while the screen of `before` stays exactly what was shown: what follows it
        is then this part's own text, screened. When this part changes how the
        tail screens - a key begun there and finished here, or a match there that
        this part breaks - the value crosses the boundary, and half of it is
        already on screen: the text part blocks, a reasoning part is withheld. A
        keyword only the two parts spell together blocks the same way.

        A part too long to screen with its tail under `fits` is screened alone,
        after its start is screened with the tail on a window that fits.
        """
        try:
            shown = self._cleaned(before)
            if self.fits is None or self.fits(before + part.content):
                both = self._cleaned(before + part.content)
                crossed = not both.startswith(shown)
                released = both[len(shown) :]
            else:
                window = self._cleaned(before + part.content[: self.tail_chars])
                crossed = not window.startswith(shown)
                released = self._cleaned(part.content)
        except GuardrailBlocked:
            if isinstance(part, TextPart):
                raise
            return None
        if not crossed:
            return released
        if isinstance(part, TextPart):
            raise GuardrailBlocked(edge="output", message=_BLOCK_MESSAGE["output"])
        return None

    def _cleaned(self, text: str) -> str:
        verdict = self.screen(text)
        # A detector here only allows or replaces; a block has raised.
        return str(verdict.replacement) if verdict.action == "replace" else text


def _screened_value(value: object, screen: TextDetector) -> object:
    """A JSON value with every string in it as the screen leaves it; a block raises.

    Each string on its own: a value split across two fields is not one a model
    writes, and joining them would hand the tool a field it never had. Keys are
    the tool's schema, not the agent's words, and are left alone.
    """
    if isinstance(value, str):
        verdict = screen(value)
        return str(verdict.replacement) if verdict.action == "replace" else value
    if isinstance(value, list):
        return [_screened_value(item, screen) for item in value]
    if isinstance(value, dict):
        return {key: _screened_value(item, screen) for key, item in value.items()}
    return value


def _screened_call(part: ToolCallPart, screen: TextDetector) -> ToolCallPart:
    """The call with its arguments screened, or the same call when nothing changed."""
    args = part.args_as_dict(raise_if_invalid=False)
    screened: dict[str, Any] = {key: _screened_value(value, screen) for key, value in args.items()}
    return part if screened == args else replace(part, args=screened)


@dataclass
class ScreenedToolArgs(AbstractCapability[object]):
    """Screen what the agent passes each tool, before anything acts on it (agenticos#2000).

    The response is screened as it arrives from the model, so the run's history,
    the tool, the stored transcript and every later request hold the screened
    arguments - one rewrite rather than one per reader. A blocked keyword raises
    :class:`GuardrailBlocked` before any tool runs.

    A streaming surface shows a call's arguments as they are written, so the
    call's start and deltas are held back until the part is complete and then
    released, screened, as one start event and its end - the treatment
    :class:`ScreenedStream` gives the answer's text.
    """

    screen: TextDetector

    async def after_model_request(
        self,
        ctx: RunContext[object],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """The response with every tool call's arguments screened."""
        parts = [
            _screened_call(part, self.screen) if isinstance(part, ToolCallPart) else part
            for part in response.parts
        ]
        return response if parts == response.parts else replace(response, parts=parts)

    async def wrap_run_event_stream(
        self,
        ctx: RunContext[object],
        *,
        stream: AsyncIterable[AgentStreamEvent],
    ) -> AsyncIterable[AgentStreamEvent]:
        """Hold each tool call until it is whole, and release it screened."""
        held: dict[int, PartStartEvent] = {}
        async for event in stream:
            match event:
                case PartStartEvent(part=ToolCallPart()):
                    held[event.index] = event
                case PartDeltaEvent(delta=ToolCallPartDelta()):
                    pass
                case PartEndEvent(part=ToolCallPart() as part):
                    screened = _screened_call(part, self.screen)
                    yield replace(held.pop(event.index), part=screened)
                    yield replace(event, part=screened)
                case _:
                    yield event


def output_screen(config: GuardrailsConfig) -> ScreenedStream | None:
    """The stream screen this configuration's output check runs, or `None` without one.

    One builder for the agent's own stream and for its delegates' (agenticos#2000):
    a delegate's text streams to the same reader as the agent's, so the agent's
    output check holds it to the same rule.
    """
    phone_regions = parse_phone_regions(config.phone_regions)
    keywords = _keywords(config.blocked_keywords_out)
    detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_out,
        redact_pii_on=config.redact_pii_out,
        phone_regions=phone_regions,
        keywords=keywords,
        edge="output",
    )
    if detector is None:
        return None
    return ScreenedStream(
        screen=detector,
        fits=(
            (lambda text: phone_text_error(text, phone_regions) is None)
            if config.redact_pii_out
            else None
        ),
        tail_chars=max([_BOUNDARY_CHARS, *(len(term) for term in keywords)]),
    )


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
    phone_regions = parse_phone_regions(config.phone_regions)

    input_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_in,
        redact_pii_on=config.redact_pii_in,
        phone_regions=phone_regions,
        keywords=_keywords(config.blocked_keywords_in),
        edge="input",
    )
    if input_detector is not None:
        edges.append(InputGuardrail(guard=input_detector))

    stream = output_screen(config)
    if stream is not None:
        edges.append(OutputGuardrail(guard=for_text(stream.screen, on_other="allow")))
        edges.append(stream)

    tool_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_tool,
        redact_pii_on=config.redact_pii_tool,
        phone_regions=phone_regions,
        keywords=_keywords(config.blocked_keywords_tool),
        edge="tool_result",
    )
    if tool_detector is not None:
        edges.append(
            ToolGuardrail(result_guard=for_tool_result_text(tool_detector, on_other="allow"))
        )

    args_detector = _edge_detector(
        redact_secrets_on=config.redact_secrets_args,
        redact_pii_on=config.redact_pii_args,
        phone_regions=phone_regions,
        keywords=_keywords(config.blocked_keywords_args),
        edge="tool_args",
    )
    if args_detector is not None:
        edges.append(ScreenedToolArgs(screen=args_detector))

    if not edges:
        return None
    return CombinedCapability(capabilities=edges)
