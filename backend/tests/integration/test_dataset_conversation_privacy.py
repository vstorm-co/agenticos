"""A dataset grant does not grant access to the private conversations copied into it."""

import uuid
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import Dataset, DatasetCase
from app.db.models.resource_grant import ResourceGrant
from app.db.models.user import User
from app.main import app
from app.schemas.dataset import (
    DatasetCaseContent,
    DatasetCaseFromMessage,
    DatasetCaseUpdate,
    DatasetCreate,
)
from app.services.dataset import DatasetService, GeneratedCase
from tests.integration.test_datasets import _rated_down_turn
from tests.integration.test_eval_suites import (
    Model,
    _agent,
    _environment,
    _finish_runs,
    _member,
    _owner,
    _suite_data,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]
__all__ = ["_environment"]


async def test_case_text_is_masked_on_every_public_read_and_export_but_not_internal_execution(
    db,
) -> None:
    owner = await _owner(db)
    viewer = await _member(db, owner, OrgRoleName.VIEWER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="conversation privacy"))
    _, answer = await _rated_down_turn(db, owner)
    case = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id, with_history=True)
    )
    await service.update_case(
        owner,
        dataset.id,
        case.case_id,
        DatasetCaseUpdate(checks=[{"type": "contains", "value": "30 days"}]),
    )
    version = (await service.read(owner, dataset.id)).latest_version
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=viewer.user_id,
            resource_type="dataset",
            resource_id=dataset.id,
            level="edit",
        )
    )
    await db.flush()
    overrides = app.dependency_overrides.copy()
    ctx = viewer
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: AsyncMock()
    app.dependency_overrides[deps.get_dataset_service] = lambda: service
    path = f"{settings.API_V1_STR}/datasets/{dataset.id}"
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for suffix in (
                "/cases",
                "/cases?version=1",
                f"/cases/{case.case_id}",
                f"/cases/{case.case_id}?version={version}",
                "/export?format=jsonl",
                "/export?format=csv",
            ):
                response = await client.get(path + suffix)
                assert response.status_code == 200, response.text
                assert case.input not in response.text
                assert case.counter_example not in response.text
            read = await service.read_case(viewer, dataset.id, case.case_id)
            assert read.masked and not read.history and not read.checks and read.note is None
            refused = await client.patch(
                f"{path}/cases/{case.case_id}", json={"input": "Overwrite hidden text"}
            )
            assert refused.status_code == 403
            # Metadata edits cannot become a back door to the full revision in their response.
            metadata = await client.patch(f"{path}/cases/{case.case_id}", json={"tags": ["refund"]})
            assert metadata.status_code == 200 and metadata.json()["masked"]
            assert case.input not in metadata.text
            for reader in (owner, replace(owner, role=OrgRoleName.VIEWER)):
                ctx = reader
                visible = await client.get(f"{path}/cases/{case.case_id}")
                assert visible.status_code == 200 and visible.json()["input"] == case.input
                assert visible.json()["masked"] is False
            ctx = await _owner(db)
            assert (await client.get(f"{path}/cases/{case.case_id}")).status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)

    # An eval still reads the question, history and expected answer from the stored row.
    from app.services.eval_suite import EvalSuiteService

    agent, _ = await _agent(db, owner)
    suites = EvalSuiteService(db)
    stored_dataset = await db.get(Dataset, dataset.id)
    assert stored_dataset is not None
    suite = await suites.create(owner, agent.id, _suite_data(stored_dataset))
    await suites.run_now(owner, agent.id, suite.id)
    prompts: list[str] = []
    await _finish_runs(db, Model(db, answer=lambda prompt: prompts.append(prompt) or "30 days"))
    assert any(case.input in prompt for prompt in prompts)
    stored = (
        await db.scalars(
            select(DatasetCase).where(
                DatasetCase.case_id == case.case_id, DatasetCase.removed_in.is_(None)
            )
        )
    ).one()
    assert stored.input == case.input


async def test_private_source_warning_names_somebody_else_but_not_the_conversation_owner(
    db,
) -> None:
    owner = await _owner(db)
    curator = await _member(db, owner, OrgRoleName.OWNER)
    viewer = await _member(db, owner, OrgRoleName.VIEWER)
    person = await db.get(User, owner.user_id)
    assert person is not None
    person.full_name = "Pat"
    _, answer = await _rated_down_turn(db, owner)
    service = DatasetService(db)
    own = await service.source_privacy(owner, answer.id)
    other = await service.source_privacy(curator, answer.id)
    assert not own.private_to_other
    assert other.private_to_other and other.owner_name == "Pat"
    with pytest.raises(NotFoundError):
        await service.source_privacy(viewer, answer.id)


async def _held(db, dataset_id) -> list[DatasetCase]:
    return list(
        await db.scalars(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset_id, DatasetCase.removed_in.is_(None))
            .order_by(DatasetCase.position)
            .execution_options(populate_existing=True)
        )
    )


async def test_a_source_check_without_a_person_or_for_an_unknown_message_finds_nothing(
    db,
) -> None:
    owner = await _owner(db)
    _, answer = await _rated_down_turn(db, owner)
    service = DatasetService(db)

    with pytest.raises(NotFoundError, match="Message not found"):
        await service.source_privacy(owner, uuid.uuid4())
    with pytest.raises(NotFoundError, match="Message not found"):
        await service.source_privacy(replace(owner, user_id=None), answer.id)


async def test_cases_from_one_conversation_are_masked_together_and_once_it_is_gone(db) -> None:
    """Cases sharing a conversation are shown or hidden by one access check; nobody, and
    then everybody once the conversation is deleted, reads a conversation case masked."""
    owner = await _owner(db)
    as_viewer = replace(owner, role=OrgRoleName.VIEWER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="one conversation"))
    _, answer = await _rated_down_turn(db, owner)
    copied = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=answer.id)
    )
    drafted = GeneratedCase(
        content=DatasetCaseContent(input="Can I return a kettle?", reference_answer="Yes."),
        source_conversation_id=answer.conversation_id,
    )
    await service.add_generated(owner, await service.lock_for_edit(owner, dataset.id), [drafted])

    shown = (await service.list_cases(as_viewer, dataset.id)).items
    hidden = await service.case_reads(replace(owner, user_id=None), await _held(db, dataset.id))
    await db.execute(delete(Conversation).where(Conversation.id == answer.conversation_id))
    gone = {
        read.case_id: read
        for read in await service.case_reads(as_viewer, await _held(db, dataset.id))
    }

    assert [read.masked for read in shown] == [False, False]
    assert [read.input for read in shown] == [copied.input, "Can I return a kettle?"]
    assert [read.masked for read in hidden] == [True, True]
    assert copied.input not in {read.input for read in hidden}
    assert gone[copied.case_id].masked
    assert gone[copied.case_id].input != copied.input


async def test_a_draft_from_another_organizations_message_is_attributed_to_nobody(db) -> None:
    owner = await _owner(db)
    stranger = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="attribution"))
    questions = []
    for ctx in (owner, stranger):
        _, answer = await _rated_down_turn(db, ctx)
        question = await db.scalar(
            select(Message).where(
                Message.conversation_id == answer.conversation_id,
                Message.content == "How long do I have to return it?",
            )
        )
        assert question is not None
        questions.append(question)
    drafts = [
        GeneratedCase(
            content=DatasetCaseContent(input=f"Drafted {index}?", reference_answer="Yes."),
            source_message_id=question.id,
        )
        for index, question in enumerate(questions)
    ]

    await service.add_generated(owner, await service.lock_for_edit(owner, dataset.id), drafts)

    held = await _held(db, dataset.id)
    assert [case.asked_by_user_id for case in held] == [owner.user_id, None]


async def test_review_hides_answers_notes_and_judge_evidence_without_runs_view(db) -> None:
    from app.db.models.case_score import CaseScore
    from app.schemas.scoring import DatasetScoring
    from app.services.scoring import ScoringService

    owner = await _owner(db)
    viewer = await _member(db, owner, OrgRoleName.VIEWER)
    service = DatasetService(db)
    dataset = await service.create(owner, DatasetCreate(name="private review"))
    run, message = await _rated_down_turn(db, owner)
    case = await service.add_from_message(
        owner, dataset.id, DatasetCaseFromMessage(message_id=message.id)
    )
    stored = CaseScore(
        organization_id=owner.organization_id,
        dataset_id=dataset.id,
        case_revision_id=case.id,
        case_id=case.case_id,
        run_id=run.id,
        agent_id=run.agent_id,
        answer="PRIVATE_ANSWER",
        scoring=DatasetScoring().model_dump(mode="json"),
        results=[
            {
                "scorer": "judge",
                "name": "PRIVATE_NAME",
                "required": True,
                "status": "fail",
                "reason": "PRIVATE_REASON",
                "rule": "PRIVATE_RULE",
                "unverified_quotes": ["PRIVATE_QUOTE"],
                "judge_said": "PRIVATE_JUDGE",
            }
        ],
        passed=False,
        human_passed=False,
        human_note="PRIVATE_NOTE",
        review_state="done",
    )
    db.add(stored)
    await db.flush()
    scores = ScoringService(db)
    visible = await scores.list_scores(owner, dataset.id)
    assert visible.items[0].answer == "PRIVATE_ANSWER"
    masked = await scores.list_scores(viewer, dataset.id)
    read = masked.items[0]
    assert read.answer_hidden and read.case_masked
    assert "PRIVATE_" not in read.model_dump_json()
    assert case.input not in read.model_dump_json()
