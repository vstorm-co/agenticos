"""Which scorers a dataset's configuration turns on, without a database.

The integration suite scores with every scorer on; these are the switches that
leave one out.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.case_score import CaseScore
from app.repositories import organization_repo
from app.schemas.scoring import ChecksScorer, DatasetScoring, TrajectoryScorer
from app.services.ai_assistance import AiAssistanceService
from app.services.scorers import CaseView, ScoredAnswer, ScoredCall
from app.services.scoring import ScoringService

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

    assert await ScoringService(AsyncMock()).evaluate(_ctx(), CASE, ANSWER, scoring) == []


async def test_a_case_with_no_expected_calls_has_no_trajectory_to_score() -> None:
    case = CaseView(**{**CASE.__dict__, "expected_tool_calls": [], "checks": []})

    assert await ScoringService(AsyncMock()).evaluate(_ctx(), case, ANSWER, DatasetScoring()) == []


async def test_the_switch_of_an_organization_that_does_not_exist_is_not_found(monkeypatch) -> None:
    monkeypatch.setattr(organization_repo, "get_by_id", AsyncMock(return_value=None))

    with pytest.raises(NotFoundError):
        await AiAssistanceService(AsyncMock()).is_enabled(organization_id=uuid.uuid4())


def test_a_score_names_its_case_and_run() -> None:
    case_id, run_id = uuid.uuid4(), uuid.uuid4()

    assert repr(CaseScore(case_id=case_id, run_id=run_id, passed=True)) == (
        f"<CaseScore(case={case_id}, run={run_id}, passed=True)>"
    )
