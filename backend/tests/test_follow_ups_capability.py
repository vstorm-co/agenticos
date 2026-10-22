"""The follow-ups capability: next steps as buttons under an answer (#2301).

The console draws whatever the tool returned, so what is asserted here is what
reaches it: the steps as the model gave them, cleaned, and a refusal the model
can act on for anything a button could not hold.
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBinding, build
from app.agents.capabilities.follow_ups import (
    FOLLOW_UPS_CAPABILITY_ID,
    FollowUps,
    FollowUpsToolset,
)
from app.agents.capabilities.follow_ups._toolset import MAX_STEP_CHARS, SetupProposal


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
                _proposal("connection", request="Gmail"),
            ],
        )

        proposals = json.loads(answered)["proposals"]
        assert [p["kind"] for p in proposals] == ["routine", "agent", "connection"]
        assert proposals[0]["cron"] == "0 7 * * 1-5"
        assert proposals[1]["cron"] is None

    @pytest.mark.parametrize(("count", "says"), [(0, "at least one"), (4, "at most 3")])
    def test_none_or_too_many_is_sent_back_to_the_model(self, count, says):
        with pytest.raises(ModelRetry, match=says):
            FollowUpsToolset[Any]().propose_setup(_ctx(), [_proposal("agent")] * count)

    def test_a_kind_the_console_cannot_draw_is_refused_by_the_schema(self):
        with pytest.raises(ValidationError):
            _proposal("webinar")
