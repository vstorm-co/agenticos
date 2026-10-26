"""The main model keeps setup cards, but never writes next-step buttons."""

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
    kept_steps,
)
from app.agents.capabilities.follow_ups._toolset import SetupProposal


def _ctx(*, retry: int = 0) -> RunContext[Any]:
    return RunContext(deps=None, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=1)


def test_main_model_never_offers_next_steps():
    [capability] = build([CapabilityBinding(capability_id=FOLLOW_UPS_CAPABILITY_ID)])
    assert isinstance(capability, FollowUps)
    toolset = capability.get_toolset()
    assert toolset is capability.get_toolset()
    assert list(toolset.tools) == ["propose_setup"]
    assert "generated separately" in capability.get_instructions()


def test_kept_steps_hold_what_a_button_can():
    assert kept_steps(["", " a ", "b", "c", "d", "x" * 81]) == ["a", "b", "c"]


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
