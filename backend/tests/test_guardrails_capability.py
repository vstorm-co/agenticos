"""The guardrails capability - what it redacts, what it blocks, and what it costs.

Most of the value here is in the refusal: a blocked prompt, answer or tool result
ends the run as `GUARDRAIL_BLOCKED` rather than completing with a refusal that reads
like any other answer. The redaction path is the opposite promise - a scrubbed key
lets the run finish - and both are checked here against a real agent run, because
the block has to *escape* `agent.run()` for the runner to record it.
"""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.capabilities import CombinedCapability
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.guardrails import InputGuardrail, OutputGuardrail, ToolGuardrail

from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get, load_builtins
from app.agents.capabilities.guardrails import (
    GuardrailBlocked,
    GuardrailsConfig,
    build_guardrails,
)
from app.agents.capabilities.guardrails._capability import _edge_detector, _keywords

pytestmark = pytest.mark.anyio

SECRET = "sk-ant-api03-ABCDEFGHIJKLMNOPQR"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


def _answers(text: str) -> FunctionModel:
    """Answer with fixed text, ignoring the prompt."""

    def respond(messages, info):  # type: ignore[no-untyped-def]
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(respond)


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
        redact_secrets_on=False, redact_pii_on=False, keywords=[], edge="input"
    )
    assert detector is None


def test_a_redactor_rewrites_a_match_and_allows_clean_text():
    detect = _edge_detector(redact_secrets_on=True, redact_pii_on=False, keywords=[], edge="input")
    assert detect is not None

    hit = detect(f"my key {SECRET} ok")
    assert hit.action == "replace"
    assert SECRET not in str(hit.replacement)

    clean = detect("nothing to redact here")
    assert clean.action == "allow"


def test_a_blocked_keyword_raises_naming_the_edge():
    detect = _edge_detector(
        redact_secrets_on=False, redact_pii_on=False, keywords=["forbidden"], edge="output"
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
        redact_secrets_on=True, redact_pii_on=True, keywords=[SECRET], edge="input"
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
    assert kinds == {InputGuardrail, OutputGuardrail, ToolGuardrail}


def test_only_the_configured_edge_is_attached():
    combined = build_guardrails(GuardrailsConfig(redact_pii_out=True))
    assert isinstance(combined, CombinedCapability)
    assert [type(edge) for edge in combined.capabilities] == [OutputGuardrail]


async def test_input_redaction_rewrites_the_prompt_the_model_sees():
    agent = _agent(GuardrailsConfig(redact_secrets_in=True), _echoes_prompt())
    result = await agent.run(f"here is {SECRET} keep it")
    assert SECRET not in result.output
    assert "[redacted:anthropic_key]" in result.output


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
