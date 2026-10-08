"""The guardrails capability - what it redacts, what it blocks, and what it costs.

Most of the value here is in the refusal: a blocked prompt, answer or tool result
ends the run as `GUARDRAIL_BLOCKED` rather than completing with a refusal that reads
like any other answer. The redaction path is the opposite promise - a scrubbed key
lets the run finish - and both are checked here against a real agent run, because
the block has to *escape* `agent.run()` for the runner to record it.

The output edge has a third promise, about the stream: nothing it would redact or
block is shown before it has run, because every surface streams the answer and the
harness guardrail only reads the finished one (agenticos#1900).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import CombinedCapability
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelMessage,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingCalls,
    DeltaThinkingPart,
    DeltaToolCall,
    DeltaToolCalls,
    FunctionModel,
)
from pydantic_ai_harness.guardrails import (
    GuardrailResult,
    InputGuardrail,
    OutputGuardrail,
    ToolGuardrail,
)

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get, load_builtins
from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    build_guardrails,
)
from app.agents.capabilities.guardrails._capability import (
    WITHHELD_REASONING,
    ScreenedStream,
    _edge_detector,
    _keywords,
)

pytestmark = pytest.mark.anyio

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQR"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _answers(text: str) -> FunctionModel:
    """Answer with fixed text, ignoring the prompt.

    Streams as well as answers whole: an output check screens the stream, which
    makes `agent.run()` stream the model's response under the hood.
    """

    def respond(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    async def stream(_messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[str]:
        yield text

    return FunctionModel(respond, stream_function=stream)


type Chunk = str | DeltaToolCalls | DeltaThinkingCalls


def _streams(*responses: Sequence[Chunk]) -> FunctionModel:
    """Stream `responses[n]` as the run's n-th model response, chunk by chunk."""

    async def stream(messages: list[ModelMessage], _info: AgentInfo) -> AsyncIterator[Chunk]:
        for chunk in responses[sum(isinstance(m, ModelResponse) for m in messages)]:
            yield chunk

    return FunctionModel(stream_function=stream)


def _echoes_prompt() -> FunctionModel:
    """Answer with the prompt text the model was actually handed."""

    def respond(messages, info):  # type: ignore[no-untyped-def]
        seen = ""
        for message in messages:
            for part in getattr(message, "parts", []):
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    seen = part.content
        return ModelResponse(parts=[TextPart(seen)])

    return FunctionModel(respond)


def _calls_tool_then_answers() -> FunctionModel:
    """Call `fetch` on the first turn, then answer once it has a result."""

    def respond(messages, info):  # type: ignore[no-untyped-def]
        called = any(
            isinstance(part, ToolCallPart)
            for message in messages
            for part in getattr(message, "parts", [])
        )
        if called:
            return ModelResponse(parts=[TextPart("answered")])
        return ModelResponse(parts=[ToolCallPart(tool_name="fetch", args={}, tool_call_id="c1")])

    return FunctionModel(respond)


def _agent(
    config: GuardrailsConfig, model: FunctionModel, *, tool_result: str | None = None
) -> Agent:
    capability = build_guardrails(config)
    agent: Agent = Agent(model=model, capabilities=[capability] if capability else [])
    if tool_result is not None:

        async def fetch() -> str:
            return tool_result

        agent.tool_plain(fetch)
    return agent


def test_keywords_split_on_comma_and_newline_and_drop_blanks():
    assert _keywords("alpha, beta\ngamma") == ["alpha", "beta", "gamma"]
    assert _keywords("  spaced  ,\n , ") == ["spaced"]
    assert _keywords("") == []


def test_an_edge_with_nothing_configured_is_not_built():
    detector = _edge_detector(
        redact_secrets_on=False, redact_pii_on=False, phone_regions=(), keywords=[], edge="input"
    )
    assert detector is None


def test_a_redactor_rewrites_a_match_and_allows_clean_text():
    detect = _edge_detector(
        redact_secrets_on=True, redact_pii_on=False, phone_regions=(), keywords=[], edge="input"
    )
    assert detect is not None

    hit = detect(f"my key {SECRET} ok")
    assert hit.action == "replace"
    assert SECRET not in str(hit.replacement)

    clean = detect("nothing to redact here")
    assert clean.action == "allow"


def test_a_blocked_keyword_raises_naming_the_edge():
    detect = _edge_detector(
        redact_secrets_on=False,
        redact_pii_on=False,
        phone_regions=(),
        keywords=["forbidden"],
        edge="output",
    )
    assert detect is not None
    with pytest.raises(GuardrailBlocked) as exc:
        detect("this is forbidden text")
    assert exc.value.edge == "output"

    assert detect("this is fine").action == "allow"


def test_the_keyword_check_reads_already_redacted_text():
    """Redaction threads forward, so the keyword check runs on the clean text.

    Both a redactor and a keyword list on one edge: the secret is scrubbed first,
    and the keyword - which does not appear in the placeholder - does not match, so
    the run is allowed with the redaction applied rather than blocked.
    """
    detect = _edge_detector(
        redact_secrets_on=True,
        redact_pii_on=True,
        phone_regions=(),
        keywords=[SECRET],
        edge="input",
    )
    assert detect is not None
    verdict = detect(f"leaking {SECRET} now")
    assert verdict.action == "replace"
    assert SECRET not in str(verdict.replacement)


def test_no_edge_configured_builds_nothing():
    assert build_guardrails(GuardrailsConfig()) is None


def test_each_configured_edge_attaches_its_harness_capability():
    combined = build_guardrails(
        GuardrailsConfig(
            blocked_keywords_in="a",
            redact_secrets_out=True,
            blocked_keywords_tool="b",
        )
    )
    assert isinstance(combined, CombinedCapability)
    kinds = {type(edge) for edge in combined.capabilities}
    assert kinds == {InputGuardrail, OutputGuardrail, ScreenedStream, ToolGuardrail}


def test_only_the_configured_edge_is_attached():
    combined = build_guardrails(GuardrailsConfig(redact_pii_out=True))
    assert isinstance(combined, CombinedCapability)
    assert [type(edge) for edge in combined.capabilities] == [OutputGuardrail, ScreenedStream]


def test_the_stream_is_left_alone_without_an_output_check():
    """Only an agent that asked for output screening pays for it in streaming."""
    combined = build_guardrails(GuardrailsConfig(redact_secrets_in=True, redact_secrets_tool=True))
    assert isinstance(combined, CombinedCapability)
    assert ScreenedStream not in {type(edge) for edge in combined.capabilities}


async def test_input_redaction_rewrites_the_prompt_the_model_sees():
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _echoes_prompt())
    result = await agent.run(f"here is {SECRET} keep it")
    assert SECRET not in result.output
    assert "[redacted:anthropic_key]" in result.output


async def test_input_pii_redaction_hides_a_phone_number_from_the_model():
    """The issue's message, run through the input edge on the default regions:
    the model is handed the placeholder, never the number."""
    agent = _agent(GuardrailsConfig(redact_pii_in=True), _echoes_prompt())
    result = await agent.run(
        "My email is jane.doe@example.com, my card number is 4111 1111 1111 1111, "
        "my SSN is 123-45-6789, and my phone number is 415-555-0132."
    )
    assert result.output == (
        "My email is [redacted:email], my card number is [redacted:credit_card], "
        "my SSN is [redacted:us_ssn], and my phone number is [redacted:phone]."
    )


async def test_output_pii_redaction_removes_a_phone_number_from_the_answer():
    agent = _agent(
        GuardrailsConfig(redact_pii_out=True, phone_regions="US"),
        _answers("Call us on 415-555-0132."),
    )
    result = await agent.run("how do I reach you?")
    assert result.output == "Call us on [redacted:phone]."


async def test_a_blocked_prompt_stops_the_run():
    agent = _agent(GuardrailsConfig(blocked_keywords_in="classified"), _answers("hi"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("this is classified information")
    assert exc.value.edge == "input"


async def test_a_blocked_output_stops_the_run():
    agent = _agent(GuardrailsConfig(blocked_keywords_out="leaked"), _answers("this is leaked"))
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("go")
    assert exc.value.edge == "output"


async def test_a_blocked_tool_result_stops_the_run():
    agent = _agent(
        GuardrailsConfig(blocked_keywords_tool="injection"),
        _calls_tool_then_answers(),
        tool_result="a page with an injection payload",
    )
    with pytest.raises(GuardrailBlocked) as exc:
        await agent.run("go")
    assert exc.value.edge == "tool_result"


async def test_tool_result_redaction_lets_the_run_finish():
    agent = _agent(
        GuardrailsConfig(redact_secrets_tool=True),
        _calls_tool_then_answers(),
        tool_result=f"the file held {SECRET}",
    )
    result = await agent.run("go")
    assert result.output == "answered"


def _build(config_blob: object) -> object:
    definition = get("guardrails")
    return definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="guardrails", config=config_blob),
            config=config_blob if isinstance(config_blob, GuardrailsConfig) else None,
        )
    )


def test_the_builder_contributes_nothing_for_a_default_config():
    assert _build(GuardrailsConfig()) is None


def test_the_builder_falls_back_to_defaults_for_a_foreign_config():
    assert _build(None) is None


def test_a_configured_binding_builds_the_capability():
    built = _build(GuardrailsConfig(redact_secrets_in=True))
    assert isinstance(built, CombinedCapability)


async def _streamed(agent: Agent, events: list[AgentStreamEvent]) -> None:
    """Drive `agent` the way every streaming surface does, collecting what it is shown.

    Appends to `events` rather than returning them, so a test of a run that raises
    can still read what was released before it did.
    """
    async with agent.iter("go") as run:
        async for node in run:
            if Agent.is_model_request_node(node) or Agent.is_call_tools_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        events.append(event)


def _shown(events: list[AgentStreamEvent]) -> str:
    """Every piece of text or reasoning a consumer of these events could display."""
    shown: list[str] = []
    for event in events:
        if isinstance(event, PartStartEvent | PartEndEvent) and isinstance(
            event.part, TextPart | ThinkingPart
        ):
            shown.append(event.part.content)
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
            shown.append(event.delta.content_delta)
        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
            shown.append(event.delta.content_delta or "")
    return "\n".join(shown)


# The secret arrives split across deltas, the way a model streams it: no one delta
# holds the whole pattern, so screening deltas one at a time would miss it.
_KEY_IN_PIECES = ["Here it is: sk-ant-api03-ABCDEF", "GHIJKLMNOPQR. Keep it safe."]


@pytest.mark.security
async def test_a_streamed_answer_never_shows_the_secret_it_redacts():
    """The reported leak: the deltas carried the key, and only `final_result` was
    redacted - so the web chat and every channel showed it while it was written."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "Here it is: [redacted:anthropic_key]. Keep it safe." in _shown(events)


async def test_text_written_before_a_tool_call_is_screened_too():
    """The harness guardrail reads only the run's output, which is the last
    response's text. A sentence before a tool call is not part of it, yet a
    streaming surface shows it and stores it in the turn."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [*_KEY_IN_PIECES, {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["answered"],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "[redacted:anthropic_key]" in _shown(events)
    assert "answered" in _shown(events)


async def test_reasoning_is_screened_like_the_answer():
    """Reasoning streams to the same reader as the answer, so it is held to the
    same rule - a key the model recalls while thinking is still a key on screen."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [
                {0: DeltaThinkingPart(content="The key was sk-ant-api03-ABCDEF")},
                {0: DeltaThinkingPart(content="GHIJKLMNOPQR, I should not repeat it.")},
                "Done.",
            ]
        ),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert SECRET not in _shown(events)
    assert "The key was [redacted:anthropic_key], I should not repeat it." in _shown(events)


def _released_text(events: list[AgentStreamEvent]) -> str:
    """The text parts as `RunFrames` and a channel's live reply join them: end to end."""
    return "".join(
        event.part.content
        for event in events
        if isinstance(event, PartEndEvent) and isinstance(event.part, TextPart)
    )


@pytest.mark.security
async def test_a_key_split_around_a_tool_call_is_redacted_where_it_completes():
    """Each half is harmless on its own; a surface that joins the parts shows both."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams(
            [
                "Here it is: sk-ant-api03-ABCDEF",
                {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")},
            ],
            ["GHIJKLMNOPQR. Keep it safe."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert "GHIJKLMNOPQR" not in _released_text(events)
    assert "[redacted:anthropic_key]" in _released_text(events)
    assert _released_text(events).endswith(". Keep it safe.")


@pytest.mark.security
async def test_a_keyword_only_two_parts_spell_together_is_blocked():
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="confidential"),
        _streams(
            ["This is confi", {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["dential."],
        ),
        tool_result="ok",
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked):
        await _streamed(agent, events)

    assert _released_text(events) == "This is confi"


async def test_the_released_tail_never_pushes_a_part_past_a_size_limit():
    """The tail is context: a part within the PII size ceiling is released even
    when the tail added to it would not be."""

    def screen(text: str) -> GuardrailResult:
        if len(text) > 30:
            raise GuardrailBlocked(edge="output", message="too long")
        return GuardrailResult.allow()

    agent = Agent(
        _streams(
            ["a" * 20, {1: DeltaToolCall(name="fetch", json_args="{}", tool_call_id="c1")}],
            ["b" * 30],
        ),
        capabilities=[ScreenedStream(screen=screen, fits=lambda text: len(text) <= 30)],
    )

    async def fetch() -> str:
        return "ok"

    agent.tool_plain(fetch)
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert _released_text(events) == "a" * 20 + "b" * 30


async def test_with_pii_redaction_the_stream_knows_the_phone_size_limit():
    capability = build_guardrails(GuardrailsConfig(redact_pii_out=True))
    assert capability is not None
    [screened] = [c for c in capability.capabilities if isinstance(c, ScreenedStream)]

    assert screened.fits is not None
    assert screened.fits("short")
    assert not screened.fits("1" * 20_000)


async def test_a_blocked_keyword_in_reasoning_withholds_the_reasoning_not_the_run():
    """Reasoning routinely restates the question. Ending a run whose answer is
    clean over a word the model only thought would refuse ordinary questions."""
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="acme"),
        _streams(
            [
                {0: DeltaThinkingPart(content="The user asks about Acme.")},
                "I can only talk about our own product.",
            ]
        ),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    assert "Acme" not in _shown(events)
    assert WITHHELD_REASONING in _shown(events)
    assert "I can only talk about our own product." in _shown(events)


async def test_a_released_part_keeps_what_came_before_it():
    """The held start event is the one released, so `previous_part_kind` survives."""
    agent = _agent(
        GuardrailsConfig(redact_secrets_out=True),
        _streams([{0: DeltaThinkingPart(content="Thinking.")}, "Answer."]),
    )
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    starts = [event for event in events if isinstance(event, PartStartEvent)]
    assert [(type(e.part), e.previous_part_kind) for e in starts] == [
        (ThinkingPart, None),
        (TextPart, "thinking"),
    ]


@pytest.mark.security
async def test_a_blocked_answer_ends_the_run_before_any_of_it_is_shown():
    """The block used to arrive after the whole answer had streamed - and been
    stored as the turn - so the refusal refused nothing."""
    agent = _agent(
        GuardrailsConfig(blocked_keywords_out="confidential"),
        _streams(["Strictly confidential: ", "Acme is buying Initech."]),
    )
    events: list[AgentStreamEvent] = []

    with pytest.raises(GuardrailBlocked) as exc:
        await _streamed(agent, events)

    assert exc.value.edge == "output"
    assert _shown(events) == ""


async def test_a_held_part_is_released_whole_and_in_place():
    """One start and one end event per part, both carrying the screened text, at
    the part's own index - what `RunFrames` and a channel's live reply read."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    released = [
        (type(event), event.index, event.part.content)
        for event in events
        if isinstance(event, PartStartEvent | PartEndEvent) and isinstance(event.part, TextPart)
    ]
    assert released == [
        (PartStartEvent, 0, "Here it is: [redacted:anthropic_key]. Keep it safe."),
        (PartEndEvent, 0, "Here it is: [redacted:anthropic_key]. Keep it safe."),
    ]
    assert not any(isinstance(event, PartDeltaEvent) for event in events)


async def test_without_an_output_check_the_answer_streams_token_by_token():
    """An agent screening only its input keeps the live stream it had."""
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _streams(["One ", "two ", "three."]))
    events: list[AgentStreamEvent] = []

    await _streamed(agent, events)

    deltas = [
        event.delta.content_delta
        for event in events
        if isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta)
    ]
    assert deltas == ["two ", "three."]


async def test_a_waited_for_answer_is_still_redacted():
    """Screening the stream changes only what a consumer of the stream sees: the
    output the run ends with is still the output guardrail's redacted answer."""
    agent = _agent(GuardrailsConfig(redact_secrets_out=True), _streams(_KEY_IN_PIECES))

    result = await agent.run("go")

    assert result.output == "Here it is: [redacted:anthropic_key]. Keep it safe."
