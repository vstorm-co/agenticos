"""Which questions a Try again note is checked against before anything is written.

The integration tests take the whole refusal; these pin the edges of the lists
it compares the note with. A question the caller may not read is never among
them: refusing a note for it would confirm a guess.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.repositories import dataset_repo, improvement_repo
from app.services import improvement_pipeline, skill_improvement
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.skill_improvement import SkillImprovementService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.MEMBER)


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), organization_id=uuid.uuid4(), dataset_id=uuid.uuid4(), dataset_version=3
    )


def _readable(*ids: uuid.UUID) -> AsyncMock:
    return AsyncMock(
        side_effect=lambda _db, _ctx, items, *_a, **_k: {i.id for i in items} & set(ids)
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

    questions = await ImprovementPipelineService(mock_db_session)._questions_of(
        _ctx(), _session(), []
    )

    assert questions == []
    version.assert_not_awaited()


async def test_a_session_whose_dataset_the_caller_may_not_read_checks_nothing(
    monkeypatch, mock_db_session
) -> None:
    session = _session()
    cases = AsyncMock()
    monkeypatch.setattr(
        dataset_repo, "get", AsyncMock(return_value=SimpleNamespace(id=session.dataset_id))
    )
    monkeypatch.setattr(improvement_pipeline, "accessible_ids", _readable())
    monkeypatch.setattr(dataset_repo, "list_cases", cases)

    questions = await ImprovementPipelineService(mock_db_session)._questions_of(
        _ctx(), session, [uuid.uuid4()]
    )

    assert questions == []
    cases.assert_not_awaited()


def _dataset(name: str, *, skill: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, latest_version=1, skill_id=uuid.uuid4() if skill else None
    )


async def test_a_skill_note_is_checked_against_what_the_next_check_may_ask_and_the_caller_reads(
    monkeypatch, mock_db_session
) -> None:
    """The next check picks, for each agent the line serves now, a dataset testing it that
    its starter may read: an agent added since the last check counts, and so does any such
    dataset; one the caller may not read, or whose version is gone, adds nothing."""
    test_set = _dataset("skill", skill=True)
    newcomer, hidden, gone = _dataset("newcomer"), _dataset("hidden"), _dataset("gone")
    monkeypatch.setattr(dataset_repo, "for_skill", AsyncMock(return_value=test_set))
    monkeypatch.setattr(
        dataset_repo,
        "testing_agent",
        AsyncMock(side_effect=[[newcomer, hidden], [gone]]),
    )
    monkeypatch.setattr(
        skill_improvement, "accessible_ids", _readable(test_set.id, newcomer.id, gone.id)
    )
    monkeypatch.setattr(
        dataset_repo,
        "get_version",
        AsyncMock(
            side_effect=lambda _db, dataset_id, *_a, **_k: (
                None if dataset_id == gone.id else SimpleNamespace(id=dataset_id)
            )
        ),
    )
    questions = {
        test_set.id: [SimpleNamespace(input="SKILL_QUESTION", improvement_partition="train")],
        newcomer.id: [
            SimpleNamespace(input="NEW_AGENT_HELD_OUT", improvement_partition="holdout"),
            SimpleNamespace(input="NEW_AGENT_TRAINING", improvement_partition="train"),
        ],
    }
    monkeypatch.setattr(
        dataset_repo,
        "list_cases",
        AsyncMock(side_effect=lambda _db, version_id, **_k: questions[version_id]),
    )
    service = SkillImprovementService(mock_db_session)
    agents = [SimpleNamespace(agent=SimpleNamespace(id=uuid.uuid4())) for _ in range(2)]
    monkeypatch.setattr(service.skill_agents, "line_agents", AsyncMock(return_value=agents))

    measured = await service._measured_questions(
        _ctx(),
        SimpleNamespace(skill=SimpleNamespace(id=uuid.uuid4()), fork_id=None),
        SimpleNamespace(organization_id=uuid.uuid4(), skill_id=uuid.uuid4()),
    )

    assert measured == ["SKILL_QUESTION", "NEW_AGENT_HELD_OUT"]
