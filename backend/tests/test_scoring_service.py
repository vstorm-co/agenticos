"""Which scorers a dataset's configuration turns on, without a database.

The integration suite scores with every scorer on; these are the switches that
leave one out.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.case_score import CaseScore
from app.repositories import agent_repo, organization_repo
from app.schemas.scoring import (
    ChecksScorer,
    DatasetScoring,
    JudgeCreate,
    JudgeScorer,
    RubricCriterion,
    TrajectoryScorer,
)
from app.services import scoring
from app.services.ai_assistance import AiAssistanceService
from app.services.scorers import (
    JUDGE_PROMPT_VERSION,
    CaseView,
    ScoredAnswer,
    ScoredCall,
    judge_criteria,
)
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

    async def test_a_run_with_no_version_pins_no_model_whatever_the_dataset_held(self) -> None:
        """A model the dataset once named for its judge is not the one the judge ran on."""
        scoring = self.SCORING.model_copy(
            update={
                "judge": self.SCORING.judge.model_copy(update={"model_profile_id": uuid.uuid4()})
            }
        )

        pin = await self._pin(MagicMock(agent_id=None, agent_version_id=None), scoring)

        assert (pin.model_profile_id, pin.agent_version_id, pin.spec_version) == (None, None, None)
        assert len(pin.rubric_hash) == 64

    async def test_a_version_no_longer_readable_pins_only_its_id(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_repo, "get_version", AsyncMock(return_value=None))
        version_id = uuid.uuid4()

        pin = await self._pin(MagicMock(agent_id=None, agent_version_id=version_id))

        assert (pin.model_profile_id, pin.agent_version_id, pin.spec_version) == (
            None,
            version_id,
            None,
        )


async def test_a_long_run_is_scored_on_its_last_answer(monkeypatch) -> None:
    """The transcript reads oldest first, so a run longer than a page reads its tail."""
    run = MagicMock(id=uuid.uuid4(), started_at=None, ended_at=None, cost_usd=None)
    turns = [MagicMock(role="assistant", content=f"answer {n}") for n in range(150)]

    async def transcript(self, ctx, run_id, *, skip=0, limit=100):
        return run, turns[skip : skip + limit], len(turns)

    monkeypatch.setattr(scoring.AgentRunnerService, "get_run_transcript", transcript)
    service = ScoringService(AsyncMock())
    monkeypatch.setattr(service, "_calls_of", AsyncMock(return_value=()))

    answer = await service.answer_of(_ctx(), run.id)

    assert answer.text == "answer 149"


async def test_a_role_that_may_not_create_agents_cannot_create_a_judge() -> None:
    """A dataset shared for editing does not make a Viewer someone who creates agents."""
    service = ScoringService(AsyncMock())
    service.datasets.get = AsyncMock(return_value=MagicMock(name="refunds"))
    viewer = AuthContext(
        user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.VIEWER
    )

    with pytest.raises(AuthorizationError):
        await service.create_judge(
            viewer, uuid.uuid4(), JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )


async def test_a_score_no_judge_graded_is_scored_again_without_asking_the_judge() -> None:
    service = ScoringService(AsyncMock())
    service.judge = MagicMock(require_runnable=AsyncMock())
    score = MagicMock(results=[{"scorer": "check", "status": "error"}])

    await service._judge_unchanged(_ctx(), score)

    service.judge.require_runnable.assert_not_awaited()


@pytest.mark.parametrize("pinned", [JUDGE_PROMPT_VERSION - 1, None])
async def test_an_eval_runs_score_graded_from_another_prompt_is_not_graded_again(pinned) -> None:
    service = ScoringService(AsyncMock())
    service.judge = MagicMock(require_runnable=AsyncMock())
    score = MagicMock(
        results=[{"scorer": "judge", "status": "error"}],
        scoring=DatasetScoring().model_dump(mode="json", by_alias=True),
        eval_run_id=uuid.uuid4(),
        judge={"prompt_version": pinned},
    )

    with pytest.raises(BadRequestError, match="asked differently") as refused:
        await service._judge_unchanged(_ctx(), score)

    assert refused.value.details["prompt_version"] == pinned


async def test_an_eval_runs_score_its_judge_ran_on_without_a_pin_is_not_graded_again() -> None:
    service = ScoringService(AsyncMock())
    service.judge = MagicMock(require_runnable=AsyncMock())
    score = MagicMock(
        results=[{"scorer": "judge", "status": "error", "judge_run_id": str(uuid.uuid4())}],
        scoring=DatasetScoring().model_dump(mode="json", by_alias=True),
        eval_run_id=uuid.uuid4(),
        judge=None,
    )

    with pytest.raises(BadRequestError, match="asked differently"):
        await service._judge_unchanged(_ctx(), score)


async def test_an_eval_runs_score_its_judge_never_ran_on_is_graded_again() -> None:
    service = ScoringService(AsyncMock())
    service.judge = MagicMock(require_runnable=AsyncMock())
    score = MagicMock(
        results=[{"scorer": "judge", "status": "skipped", "judge_run_id": None}],
        scoring=DatasetScoring().model_dump(mode="json", by_alias=True),
        eval_run_id=uuid.uuid4(),
        judge=None,
    )

    await service._judge_unchanged(_ctx(), score)

    service.judge.require_runnable.assert_awaited_once()
