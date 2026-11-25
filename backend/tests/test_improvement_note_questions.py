"""Which questions a Try again note is checked against before anything is written.

The integration tests take the whole refusal; these pin the edges of the lists
it compares the note with.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.repositories import dataset_repo, improvement_repo, skill_check_repo
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.skill_improvement import SkillImprovementService

pytestmark = pytest.mark.anyio


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), organization_id=uuid.uuid4(), dataset_id=uuid.uuid4(), dataset_version=3
    )


async def test_an_attempt_already_drawn_is_checked_against_its_stored_draw(
    monkeypatch, mock_db_session
) -> None:
    """Try again on an attempt whose row exists reuses that row and its draw, so the note
    is checked against exactly the questions it will be measured on."""
    stored = [uuid.uuid4(), uuid.uuid4()]
    monkeypatch.setattr(
        improvement_repo,
        "get_iteration",
        AsyncMock(return_value=SimpleNamespace(holdout_case_ids=stored)),
    )

    kept = await ImprovementPipelineService(mock_db_session)._kept_aside(_session(), 2, set())

    assert kept == stored


async def test_an_attempt_keeping_nothing_aside_checks_the_note_against_nothing(
    monkeypatch, mock_db_session
) -> None:
    version = AsyncMock()
    monkeypatch.setattr(dataset_repo, "get_version", version)

    questions = await ImprovementPipelineService(mock_db_session)._questions_of(_session(), [])

    assert questions == []
    version.assert_not_awaited()


async def test_a_dataset_version_that_is_gone_adds_no_questions(
    monkeypatch, mock_db_session
) -> None:
    """A check's agent may have answered from a dataset deleted since; the skill's own
    test questions are still read, every one of them."""
    test_set, gone = SimpleNamespace(id=uuid.uuid4(), latest_version=1), uuid.uuid4()
    monkeypatch.setattr(dataset_repo, "for_skill", AsyncMock(return_value=test_set))
    monkeypatch.setattr(
        skill_check_repo,
        "list_agents",
        AsyncMock(return_value=[SimpleNamespace(dataset_id=gone, dataset_version=4)]),
    )
    pinned = SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(
        dataset_repo,
        "get_version",
        AsyncMock(
            side_effect=lambda _db, dataset_id, *_a, **_k: None if dataset_id == gone else pinned
        ),
    )
    monkeypatch.setattr(
        dataset_repo,
        "list_cases",
        AsyncMock(
            return_value=[
                SimpleNamespace(input="What is the refund window?", improvement_partition="train")
            ]
        ),
    )
    service = SkillImprovementService(mock_db_session)
    monkeypatch.setattr(service, "_check", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))

    questions = await service._measured_questions(
        SimpleNamespace(organization_id=uuid.uuid4(), skill_id=uuid.uuid4())
    )

    assert questions == ["What is the refund window?"]
