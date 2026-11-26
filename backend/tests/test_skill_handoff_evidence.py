"""What a skill learns from when an agent's Improve hands it over.

The agent's session found the skill's problems in failed test questions of its own
dataset's training partition. Those answers are the skill's evidence too, but only
the ones that used the skill, and only for a caller who may read them.
"""

import uuid
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import AuthorizationError
from app.repositories import improvement_repo, skill_usage_repo
from app.services.authoring_evidence import EvidencePack, EvidenceService, PackedRun

pytestmark = pytest.mark.anyio

AGENT = uuid.uuid4()
SKILL = uuid.uuid4()
SESSION = uuid.uuid4()


def _run(
    *, status: str, kind: Literal["chat", "train_eval"] = "train_eval", number: int = 3
) -> PackedRun:
    return PackedRun(
        run_id=uuid.uuid4(),
        conversation_id=None,
        status=status,
        rating=0,
        comments=[],
        prompt="Quote 500 flyers",
        answer="Total (ex VAT): £75.00",
        calls=[],
        error=None,
        evidence_kind=kind,
        number=number,
    )


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(organization_id=uuid.uuid4())


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, mock_db_session) -> EvidenceService:
    monkeypatch.setattr(
        improvement_repo, "get_run", AsyncMock(return_value=SimpleNamespace(agent_id=AGENT))
    )
    return EvidenceService(mock_db_session)


async def test_only_failed_training_answers_that_used_the_skill_are_handed_over(
    service, monkeypatch
) -> None:
    used, unused, passed, chat = (
        _run(status="train_eval_failure"),
        _run(status="train_eval_failure"),
        _run(status="train_eval_reviewed"),
        _run(status="failed", kind="chat"),
    )
    monkeypatch.setattr(
        EvidenceService,
        "for_improvement",
        AsyncMock(return_value=EvidencePack(runs=[used, unused, passed, chat])),
    )
    uses = AsyncMock(
        return_value=[
            SimpleNamespace(run_id=run.run_id, agent_id=AGENT, loaded=True, resource_reads=[])
            for run in (used, passed, chat)
        ]
    )
    monkeypatch.setattr(skill_usage_repo, "uses_in_runs", uses)

    handed = await service.for_skill_handoff(_ctx(), SKILL, SESSION)

    assert [run.run_id for run in handed] == [used.run_id]
    assert (handed[0].skill_use, handed[0].via_delegate, handed[0].number) == ("used", False, 0)
    asked = uses.await_args
    assert asked is not None and asked.kwargs["run_ids"] == [used.run_id, unused.run_id]


async def test_a_caller_who_may_not_read_the_session_s_dataset_reads_none(
    service, monkeypatch
) -> None:
    monkeypatch.setattr(
        EvidenceService,
        "for_improvement",
        AsyncMock(side_effect=AuthorizationError(message="No", details={})),
    )

    assert await service.for_skill_handoff(_ctx(), SKILL, SESSION) == []


async def test_a_session_that_no_longer_exists_hands_over_nothing(service, monkeypatch) -> None:
    monkeypatch.setattr(improvement_repo, "get_run", AsyncMock(return_value=None))

    assert await service.for_skill_handoff(_ctx(), SKILL, SESSION) == []
