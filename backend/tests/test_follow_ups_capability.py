"""The follow-ups capability: next steps as buttons under an answer (#2301).

The console draws whatever the tool returned, so what is asserted here is what
reaches it: the steps as the model gave them, cleaned, and a refusal the model
can act on for anything a button could not hold.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._ambient import AmbientCallSkipped
from app.agents.capabilities._registry import CapabilityBinding, build
from app.agents.capabilities.follow_ups import (
    FOLLOW_UPS_CAPABILITY_ID,
    FOLLOW_UPS_MODEL_RESOURCE,
    FollowUps,
    FollowUpsToolset,
    kept_steps,
)
from app.agents.capabilities.follow_ups._toolset import MAX_STEP_CHARS, SetupProposal
from app.agents.deps import AgentDeps


def _ctx(*, retry: int = 0) -> RunContext[Any]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)


def _suggest(steps: list[str], *, retry: int = 0) -> str:
    return FollowUpsToolset[Any]().suggest_next_steps(_ctx(retry=retry), steps)


class TestSuggestingNextSteps:
    def test_the_steps_reach_the_console_trimmed_with_blanks_dropped(self):
        answered = _suggest(["  Make it a table ", "", "Zrób to co poniedziałek"])

        assert json.loads(answered) == {"steps": ["Make it a table", "Zrób to co poniedziałek"]}
        # Kept readable in the transcript, not escaped.
        assert "poniedziałek" in answered

    @pytest.mark.parametrize(
        ("steps", "says"),
        [
            ([" ", ""], "at least one"),
            (["a", "b", "c", "d"], "at most 3"),
            (["x" * (MAX_STEP_CHARS + 1)], "at most 80 characters"),
        ],
    )
    def test_a_step_no_button_could_hold_is_sent_back_to_the_model(self, steps, says):
        with pytest.raises(ModelRetry, match=says):
            _suggest(steps)

    def test_the_last_attempt_says_so_rather_than_ending_the_run(self):
        assert "at least one" in _suggest([], retry=1)


class TestTheCapability:
    def test_it_builds_once_and_offers_its_two_tools(self):
        [capability] = build([CapabilityBinding(capability_id=FOLLOW_UPS_CAPABILITY_ID)])

        assert isinstance(capability, FollowUps)
        toolset = capability.get_toolset()
        assert toolset is capability.get_toolset()
        assert list(toolset.tools) == ["suggest_next_steps", "propose_setup"]

    def test_with_a_model_of_its_own_the_agent_is_not_offered_the_steps(self):
        """The model writes them after the answer; the agent keeps proposing setups (#2301)."""
        [capability] = build(
            [CapabilityBinding(capability_id=FOLLOW_UPS_CAPABILITY_ID)],
            resources={FOLLOW_UPS_MODEL_RESOURCE: TestModel()},
        )

        assert isinstance(capability, FollowUps)
        assert capability.model is not None
        assert list(capability.get_toolset().tools) == ["propose_setup"]

    def test_a_resource_that_is_no_model_is_ignored(self):
        [capability] = build(
            [CapabilityBinding(capability_id=FOLLOW_UPS_CAPABILITY_ID)],
            resources={FOLLOW_UPS_MODEL_RESOURCE: "not a model"},
        )

        assert isinstance(capability, FollowUps)
        assert capability.model is None


_WRITER = "app.agents.capabilities.follow_ups._capability.run_ambient_agent"


def _turn(answer: str, *, called: bool = False) -> ModelResponse:
    parts: list[Any] = [TextPart(content=answer)] if answer else []
    if called:
        parts.append(ToolCallPart(tool_name="web_search", args={}))
    return ModelResponse(parts=parts)


async def _after(
    capability: FollowUps, response: ModelResponse, *, request: str = "Compare the vendors"
) -> AgentDeps:
    deps = AgentDeps()
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    asked = SimpleNamespace(
        messages=[
            ModelRequest(parts=[UserPromptPart(content=request)]),
            ModelResponse(parts=[TextPart(content="earlier")]),
        ]
    )
    returned = await capability.after_model_request(ctx, request_context=asked, response=response)
    assert returned is response
    return deps


@pytest.mark.anyio
class TestNextStepsWrittenAfterTheAnswer:
    async def test_the_steps_are_written_from_the_request_and_the_answer(self):
        writer = AsyncMock(return_value=SimpleNamespace(steps=[" Make it a table ", "x" * 81]))
        with patch(_WRITER, new=writer):
            deps = await _after(FollowUps(model=TestModel()), _turn("Here is the comparison."))

        assert deps.next_steps is not None
        assert deps.next_steps.steps == ["Make it a table"]
        assert deps.next_steps.call_id.startswith("next_steps_")
        prompt = writer.await_args.kwargs["user_prompt"]
        assert "Compare the vendors" in prompt and "Here is the comparison." in prompt

    async def test_none_are_written_without_a_model_or_before_the_answer(self):
        writer = AsyncMock()
        with patch(_WRITER, new=writer):
            assert (await _after(FollowUps(), _turn("Done."))).next_steps is None
            assert (
                await _after(FollowUps(model=TestModel()), _turn("Looking.", called=True))
            ).next_steps is None
            assert (await _after(FollowUps(model=TestModel()), _turn(""))).next_steps is None

        writer.assert_not_awaited()

    @pytest.mark.parametrize(
        "outcome",
        [
            SimpleNamespace(steps=[]),
            AmbientCallSkipped("at a cap"),
            RuntimeError("the provider is down"),
        ],
    )
    async def test_steps_that_could_not_be_written_cost_the_buttons_only(self, outcome):
        writer = AsyncMock(side_effect=outcome if isinstance(outcome, Exception) else None)
        if not isinstance(outcome, Exception):
            writer.return_value = outcome
        with patch(_WRITER, new=writer):
            deps = await _after(FollowUps(model=TestModel()), _turn("Done."))

        assert deps.next_steps is None

    async def test_a_run_with_no_request_still_reads_the_answer(self):
        writer = AsyncMock(return_value=SimpleNamespace(steps=["Again"]))
        deps = AgentDeps()
        ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
        with patch(_WRITER, new=writer):
            await FollowUps(model=TestModel()).after_model_request(
                ctx,
                request_context=SimpleNamespace(
                    messages=[ModelRequest(parts=[UserPromptPart(content=["an image"])])]
                ),
                response=_turn("Done."),
            )

        assert "The request:\n\n" in writer.await_args.kwargs["user_prompt"]


def test_kept_steps_hold_what_a_button_can():
    assert kept_steps(["", " a ", "b", "c", "d"]) == ["a", "b", "c"]


def _proposal(kind: str, **overrides: object) -> SetupProposal:
    values: dict[str, object] = {
        "kind": kind,
        "title": f"A {kind}",
        "why": "Because you said so",
        "request": "Summarise new tickets",
    }
    values.update(overrides)
    return SetupProposal.model_validate(values)


class TestProposingSetup:
    def test_the_proposals_reach_the_console_as_given(self):
        answered = FollowUpsToolset[Any]().propose_setup(
            _ctx(),
            [
                _proposal("routine", cron="0 7 * * 1-5"),
                _proposal("agent"),
                _proposal("connection", request="Gmail", server="com.mintmcp/gmail"),
            ],
        )

        proposals = json.loads(answered)["proposals"]
        assert [p["kind"] for p in proposals] == ["routine", "agent", "connection"]
        assert proposals[0]["cron"] == "0 7 * * 1-5"
        assert proposals[1]["cron"] is None
        # The key the card resolves to a logo and a one-click connect.
        assert proposals[2]["server"] == "com.mintmcp/gmail"
        assert proposals[1]["server"] is None

    @pytest.mark.parametrize(("count", "says"), [(0, "at least one"), (4, "at most 3")])
    def test_none_or_too_many_is_sent_back_to_the_model(self, count, says):
        with pytest.raises(ModelRetry, match=says):
            FollowUpsToolset[Any]().propose_setup(_ctx(), [_proposal("agent")] * count)

    def test_a_kind_the_console_cannot_draw_is_refused_by_the_schema(self):
        with pytest.raises(ValidationError):
            _proposal("webinar")
