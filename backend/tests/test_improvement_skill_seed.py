"""What a skill's Improve is handed from an agent's session, and what it is not.

The skill's check grades answers to stored held-out questions and to every
question of a skill's own test set. A quote from such an answer, handed to the
skill's improver, would let it fit what its own check then measures.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.repositories import authoring_repo, eval_run_repo
from app.services.authoring_worker import _seed_section
from app.services.improvement_skills import ImprovementSkillService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

SKILL = uuid.uuid4()


def _found(*problems: tuple[str, list[tuple[uuid.UUID, str]]]) -> SimpleNamespace:
    """An authoring request whose report names problems in `SKILL`, each with its quotes."""
    return SimpleNamespace(
        report={
            "skill_problems": [
                {
                    "skill_id": str(SKILL),
                    "problem": problem,
                    "evidence": [{"run_id": str(run), "quote": quote} for run, quote in cited],
                }
                for problem, cited in problems
            ]
        }
    )


async def _seed(monkeypatch, db, requests, measured):
    monkeypatch.setattr(authoring_repo, "requests_of_improvement", AsyncMock(return_value=requests))
    monkeypatch.setattr(
        eval_run_repo, "answers_to_measured_questions", AsyncMock(return_value=measured)
    )
    monkeypatch.setattr(ImprovementSkillService, "_read_fork", AsyncMock(return_value=None))
    return await ImprovementSkillService(db).seed(
        SimpleNamespace(organization_id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4()),
        uuid.uuid4(),
        SKILL,
        base_version_id=None,
    )


async def test_a_problem_citing_an_answer_the_check_grades_never_reaches_the_improver(
    monkeypatch, mock_db_session
):
    """Its wording was written from every answer it cites, so it goes whole: a problem
    that also cites an admissible answer is withheld as well."""
    learned, kept_aside, chat = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    requests = [
        _found(
            (
                "The window is wrong",
                [(kept_aside, "HELD_OUT_ANSWER"), (learned, "TRAIN_ANSWER_TOO")],
            ),
            ("Only seen where it is graded", [(kept_aside, "HELD_OUT_ONLY")]),
            ("Learned from training", [(learned, "TRAIN_ANSWER")]),
            ("Said in a conversation", [(chat, "CHAT_ANSWER")]),
        )
    ]

    seed = await _seed(monkeypatch, mock_db_session, requests, {kept_aside})
    prompt = _seed_section({"problems": seed.problems, "quotes": seed.quotes})

    assert seed.problems == ["Learned from training", "Said in a conversation"]
    assert seed.quotes == ["TRAIN_ANSWER", "CHAT_ANSWER"]
    assert set(seed.run_ids) == {learned, chat}
    assert seed.withheld == 2
    assert "HELD_OUT" not in prompt
    assert "The window is wrong" not in prompt and "TRAIN_ANSWER_TOO" not in prompt
    assert "TRAIN_ANSWER" in prompt and "CHAT_ANSWER" in prompt


async def test_a_seed_with_every_problem_withheld_adds_nothing_to_the_prompt(
    monkeypatch, mock_db_session
):
    """Less to start from is the price of a check that measures what it was not shown."""
    kept_aside = uuid.uuid4()

    seed = await _seed(
        monkeypatch,
        mock_db_session,
        [_found(("The window is wrong", [(kept_aside, "HELD_OUT_ANSWER")]))],
        {kept_aside},
    )

    assert (seed.problems, seed.quotes, seed.run_ids, seed.withheld) == ([], [], [], 1)
    assert _seed_section({"problems": seed.problems, "quotes": seed.quotes, "withheld": 1}) == ""
