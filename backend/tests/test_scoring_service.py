"""Which scorers a dataset's configuration turns on, without a database.

The integration suite scores with every scorer on; these are the switches that
leave one out.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.case_score import CaseScore
from app.repositories import agent_repo, organization_repo
from app.schemas.scoring import (
    ChecksScorer,
    DatasetScoring,
    JudgeScorer,
    RubricCriterion,
    TrajectoryScorer,
)
from app.services.ai_assistance import AiAssistanceService
from app.services.scorers import CaseView, ScoredAnswer, ScoredCall, judge_criteria
from app.services.scoring import Evaluation, ScoringService

pytestmark = pytest.mark.anyio

CASE = CaseView(
    input="Refund window?",
    history=[],
    reference_answer=None,
    counter_example=None,
    expected_tool_calls=[{"tool": "search_kb", "args": {}}],
    order_mode="any",
    checks=[{"type": "contains", "value": "days"}],
)
ANSWER = ScoredAnswer(text="thirty days", calls=(ScoredCall(tool="search_kb", args={}),))


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


async def test_switched_off_scorers_leave_no_result() -> None:
    scoring = DatasetScoring(
        checks=ChecksScorer(enabled=False), trajectory=TrajectoryScorer(enabled=False)
    )

    assert await ScoringService(AsyncMock()).evaluate(_ctx(), CASE, ANSWER, scoring) == Evaluation(
        []
    )


async def test_a_case_with_no_expected_calls_has_no_trajectory_to_score() -> None:
    case = CaseView(**{**CASE.__dict__, "expected_tool_calls": [], "checks": []})

    assert await ScoringService(AsyncMock()).evaluate(
        _ctx(), case, ANSWER, DatasetScoring()
    ) == Evaluation([])


async def test_the_switch_of_an_organization_that_does_not_exist_is_not_found(monkeypatch) -> None:
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))

    with pytest.raises(NotFoundError):
        await AiAssistanceService(AsyncMock()).is_enabled(organization_id=uuid.uuid4())


def test_a_score_names_its_case_and_run() -> None:
    case_id, run_id = uuid.uuid4(), uuid.uuid4()

    assert repr(CaseScore(case_id=case_id, run_id=run_id, passed=True)) == (
        f"<CaseScore(case={case_id}, run={run_id}, passed=True)>"
    )


class TestJudgePin:
    """Which judge a score names when the run cannot say which version it was."""

    SCORING = DatasetScoring(
        judge=JudgeScorer(
            enabled=True, criteria=[RubricCriterion(name="tone", description="Polite")]
        )
    )

    async def _pin(self, run: MagicMock, scoring: DatasetScoring = SCORING):
        criteria = judge_criteria(CASE, scoring, [])
        return await ScoringService(AsyncMock())._pin(_ctx(), run, criteria, scoring)

    async def test_a_run_with_no_version_pins_the_model_the_dataset_chose(self) -> None:
        profile = uuid.uuid4()
        scoring = self.SCORING.model_copy(
            update={"judge": self.SCORING.judge.model_copy(update={"model_profile_id": profile})}
        )

        pin = await self._pin(MagicMock(agent_version_id=None), scoring)

        assert (pin.model_profile_id, pin.agent_version_id, pin.spec_version) == (
            profile,
            None,
            None,
        )
        assert len(pin.rubric_hash) == 64

    async def test_a_version_no_longer_readable_pins_only_its_id(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))
        version_id = uuid.uuid4()

        pin = await self._pin(MagicMock(agent_version_id=version_id))

        assert (pin.model_profile_id, pin.agent_version_id, pin.spec_version) == (
            None,
            version_id,
            None,
        )
