"""What an improvement session's knowledge sort reads, and how it counts what it found.

A session that learns from evals has failed training answers and no chat answer:
those are sorted too, stay the improver's, and count as missing knowledge when the
classifier read them so.
"""

import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.permissions import Scope
from app.repositories import knowledge_base_repo, knowledge_gap_repo
from app.schemas.knowledge_gap import GapCause
from app.services import improvement_pipeline
from app.services.authoring_evidence import EvidencePack, PackedRun
from app.services.improvement_pipeline import (
    UNHELD_KEYS,
    ImprovementPipelineService,
    KnowledgeSources,
)
from app.services.knowledge_gaps import KnowledgeGapService

pytestmark = pytest.mark.anyio


def _run(
    kind: Literal["chat", "train_eval"], *, status: str = "completed", rating: int = 0
) -> PackedRun:
    return PackedRun(
        run_id=uuid.uuid4(),
        conversation_id=None,
        status=status,
        rating=rating,
        comments=[],
        prompt="How long does it take?",
        answer="The documents do not state it.",
        calls=[],
        error=None,
        evidence_kind=kind,
    )


def _service(
    mock_db_session: MagicMock, pack: EvidencePack, monkeypatch: pytest.MonkeyPatch
) -> ImprovementPipelineService:
    service = ImprovementPipelineService(mock_db_session)
    monkeypatch.setattr(service.authoring.evidence, "for_improvement", AsyncMock(return_value=pack))
    monkeypatch.setattr(service.authoring.evidence, "forget_erased", AsyncMock(return_value=pack))
    return service


async def test_a_session_sorts_its_failed_training_answers_beside_its_bad_chat_answers(
    mock_db_session, monkeypatch
) -> None:
    rated_down = _run("chat", rating=-1)
    rated_up = _run("chat", rating=1)
    failed = _run("train_eval", status="train_eval_failure")
    reviewed = _run("train_eval", status="train_eval_reviewed")
    pack = EvidencePack(runs=[rated_down, rated_up, failed, reviewed])
    kb = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    message = uuid.uuid4()
    monkeypatch.setattr(knowledge_base_repo, "get_by_ids", AsyncMock(return_value={kb.id: kb}))
    monkeypatch.setattr(improvement_pipeline, "writable_kb", AsyncMock(return_value=True))
    monkeypatch.setattr(
        knowledge_gap_repo, "answers_for_runs", AsyncMock(return_value={rated_down.run_id: message})
    )
    ctx = SimpleNamespace(organization_id=kb.organization_id, scope_for=lambda perm: Scope.ALL)
    agent = SimpleNamespace(draft_spec={"name": "Clerk", "collection_ids": [str(kb.id)]})

    sources = await _service(mock_db_session, pack, monkeypatch)._knowledge_sources(
        ctx, agent, uuid.uuid4()
    )

    assert sources == KnowledgeSources(
        [kb.id], [message], [failed.run_id], [rated_down.run_id, failed.run_id]
    )


async def test_a_session_with_nothing_bad_to_sort_reads_no_knowledge_base(
    mock_db_session, monkeypatch
) -> None:
    pack = EvidencePack(
        runs=[_run("chat", rating=1), _run("train_eval", status="train_eval_reviewed")]
    )
    bases = AsyncMock()
    monkeypatch.setattr(knowledge_base_repo, "get_by_ids", bases)
    ctx = SimpleNamespace(organization_id=uuid.uuid4(), scope_for=lambda perm: Scope.ALL)

    sources = await _service(mock_db_session, pack, monkeypatch)._knowledge_sources(
        ctx, SimpleNamespace(draft_spec={}), uuid.uuid4()
    )

    assert sources == KnowledgeSources([], [], [], [])
    bases.assert_not_awaited()


async def test_training_answers_stay_the_improver_s_and_count_as_missing_knowledge(
    mock_db_session, monkeypatch
) -> None:
    chat = _run("chat", rating=-1)
    silent = _run("train_eval", status="train_eval_failure")
    wrong = _run("train_eval", status="train_eval_failure")
    covered = _run("train_eval", status="train_eval_failure")
    pack = EvidencePack(runs=[chat, silent, wrong, covered])
    kb, message, topic, done = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    service = _service(mock_db_session, pack, monkeypatch)
    sources = AsyncMock(
        return_value=KnowledgeSources(
            [kb],
            [message],
            [silent.run_id, wrong.run_id, covered.run_id],
            [chat.run_id, silent.run_id, wrong.run_id, covered.run_id],
        )
    )
    monkeypatch.setattr(service, "knowledge_sources", sources)
    monkeypatch.setattr(
        KnowledgeGapService,
        "causes",
        AsyncMock(return_value={message: GapCause(message_id=message, branch="missing_knowledge")}),
    )
    monkeypatch.setattr(
        KnowledgeGapService,
        "eval_causes",
        AsyncMock(
            return_value={
                silent.run_id: ("missing_knowledge", "nothing states it"),
                wrong.run_id: ("agent", None),
                covered.run_id: ("missing_knowledge", "nothing stated it"),
            }
        ),
    )
    monkeypatch.setattr(
        knowledge_gap_repo, "answers_for_runs", AsyncMock(return_value={chat.run_id: message})
    )
    monkeypatch.setattr(
        knowledge_gap_repo,
        "topic_of_runs",
        AsyncMock(return_value={silent.run_id: topic, covered.run_id: done}),
    )
    monkeypatch.setattr(
        knowledge_gap_repo, "covering_documents", AsyncMock(return_value={done: object()})
    )

    agent, missing, excluded = await service._knowledge_branches(
        SimpleNamespace(organization_id=uuid.uuid4()),
        SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4()),
    )

    # Three training answers stay the improver's; the chat answer missing knowledge leaves it.
    assert agent == 3
    # The chat answer and the training answer whose topic no document covers yet.
    assert missing == 2
    assert excluded == [message]


@pytest.mark.parametrize(
    ("kind", "rating", "eval_branch", "chat_branch", "expected"),
    [
        ("train_eval", 0, "missing_knowledge", None, ("missing_knowledge", "why")),
        ("train_eval", 0, "not_a_problem", None, ("agent", None)),
        ("train_eval", 0, None, None, ("agent", None)),
        ("chat", 1, None, "agent", ("not_a_problem", None)),
        ("chat", -1, None, "missing_knowledge", ("missing_knowledge", "why")),
        ("chat", -1, None, None, ("unknown", None)),
    ],
)
def test_each_source_example_says_where_its_fix_belongs(
    kind, rating, eval_branch, chat_branch, expected
) -> None:
    item = _run(kind, rating=rating)
    message = uuid.uuid4()
    causes = (
        {message: GapCause(message_id=message, branch=chat_branch, reason="why")}
        if chat_branch
        else {}
    )
    answered = {item.run_id: (eval_branch, "why")} if eval_branch else {}

    assert (
        ImprovementPipelineService._evidence_branch(
            item, causes, {item.run_id: message} if causes else {}, answered
        )
        == expected
    )


def test_an_answer_missing_only_keys_no_source_holds_is_missing_knowledge() -> None:
    item = replace(_run("train_eval"), knowledge_only=True, uncovered_keys=("Due date",))

    assert ImprovementPipelineService._evidence_branch(item, {}, {}, {}) == (
        "missing_knowledge",
        UNHELD_KEYS,
    )
    assert ImprovementPipelineService._evidence_branch(
        item, {}, {}, {item.run_id: ("missing_knowledge", "why")}
    ) == ("missing_knowledge", "why")
