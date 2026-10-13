"""Deciding generated cases, against Postgres.

The claims a mocked session cannot make:

- nothing a generator drafted reaches a dataset until a person accepts it, and
  a dismissed draft leaves no trace at all - no case, no version, no row;
- one Accept is one new version, whatever it carried, holding `synthetic` cases
  that keep the document, run or conversation they were drafted from;
- a reviewer's edit is what lands, redacted like any other way in;
- a draft decided twice is decided once;
- only a member who may edit the dataset sees or decides its drafts, and a grant
  is what lets a Viewer do it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import func, select

from app.core.exceptions import NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.case_generation import CaseOrigin, CaseProposal, GenerationStatus
from app.db.models.dataset import DatasetVersion
from app.db.models.rag_document import DocumentStatus
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.schemas.case_generation import (
    CaseProposalAccept,
    CaseProposalDecision,
    CaseProposalDismiss,
)
from app.schemas.dataset import DatasetCaseContent, DatasetCaseUpdate, DatasetCreate
from app.services.case_generation import CaseGenerationService
from app.services.case_generation.facade import INTERRUPTED
from app.services.conversation import ConversationService
from app.services.dataset import DatasetService
from app.services.personal_data import PersonalDataService
from tests.integration import case_generation_world as world

pytestmark = pytest.mark.anyio


async def _setup(db):
    person = await world.user(db)
    org = await world.org(db, person)
    owner = await world.member(db, org, OrgRoleName.OWNER, person)
    agent = await world.agent(db, org)
    dataset = await DatasetService(db).create(owner, DatasetCreate(name="support"))
    return owner, org, agent, dataset


def _accept(*ids, content: DatasetCaseContent | None = None) -> CaseProposalAccept:
    return CaseProposalAccept(
        items=[CaseProposalDecision(id=proposal_id, content=content) for proposal_id in ids]
    )


async def test_drafts_wait_outside_the_dataset_until_accepted(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    await world.proposals(db, org, dataset, agent, 3)

    read = await DatasetService(db).read(owner, dataset.id)
    cases = await DatasetService(db).list_cases(owner, dataset.id)

    assert (read.latest_version, read.case_count, read.pending_proposals) == (0, 0, 3)
    assert cases.items == []


async def test_one_accept_is_one_version_of_synthetic_cases_that_keep_their_source(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    collection = await world.collection(db, org)
    document = await world.document(db, collection, DocumentStatus.DONE, "handbook.md")
    customer = await world.user(db)
    run, conversation, asked = await world.asked(db, org, agent, customer, "Refund?", minutes=1)
    _, from_docs = await world.proposals(
        db,
        org,
        dataset,
        agent,
        2,
        origin=CaseOrigin.KNOWLEDGE,
        source_document_id=document.id,
        reference_answer="Returns are accepted within 30 days.",
        tags=["knowledge"],
    )
    _, from_chat = await world.proposals(
        db,
        org,
        dataset,
        agent,
        1,
        source_run_id=run.id,
        source_conversation_id=conversation.id,
        source_message_id=asked.id,
    )

    service = CaseGenerationService(db, vector_store=MagicMock())
    version = await service.accept(
        owner, dataset.id, _accept(from_docs[1].id, from_chat[0].id, from_docs[0].id)
    )

    assert (version.number, version.change, version.changed_cases) == (1, "generate", 3)
    cases = (await DatasetService(db).list_cases(owner, dataset.id)).items
    assert {case.source for case in cases} == {"synthetic"}
    assert [case.input for case in cases] == ["question 1", "question 0", "question 0"]
    knowledge = [case for case in cases if case.source_document_id == document.id]
    assert len(knowledge) == 2
    assert {case.reference_answer for case in knowledge} == {"Returns are accepted within 30 days."}
    assert [case.tags for case in knowledge] == [["knowledge"], ["knowledge"]]
    chat = next(case for case in cases if case.source_run_id == run.id)
    assert (chat.source_conversation_id, chat.source_message_id) == (conversation.id, asked.id)
    assert await db.scalar(select(func.count(CaseProposal.id))) == 0
    assert (await DatasetService(db).read(owner, dataset.id)).pending_proposals == 0


async def test_an_edited_draft_lands_as_edited_and_redacted(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    _, drafted = await world.proposals(db, org, dataset, agent, 1)
    key = "ghp_" + "a" * 36

    await CaseGenerationService(db, vector_store=MagicMock()).accept(
        owner,
        dataset.id,
        _accept(drafted[0].id, content=DatasetCaseContent(input=f"Use {key} please", tags=["x"])),
    )

    (case,) = (await DatasetService(db).list_cases(owner, dataset.id)).items
    assert key not in case.input
    assert "[redacted:" in case.input
    assert case.tags == ["x"]
    audit = (
        await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.version_created"
            )
        )
    ).scalar_one()
    assert audit["change"] == "generate"
    assert audit["redacted_secrets"] == 1


async def test_a_dismissed_draft_leaves_no_trace(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    generation, drafted = await world.proposals(db, org, dataset, agent, 2)
    service = CaseGenerationService(db, vector_store=MagicMock())

    await service.dismiss(owner, dataset.id, CaseProposalDismiss(ids=[drafted[0].id]))

    assert await db.scalar(select(func.count(DatasetVersion.id))) == 0
    remaining = await service.list_proposals(owner, dataset.id)
    assert [item.id for item in remaining.items] == [drafted[1].id]
    await db.refresh(generation)
    assert (generation.accepted_count, generation.dismissed_count) == (0, 1)
    audit = (
        await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.action == "dataset.proposals_dismissed"
            )
        )
    ).scalar_one()
    assert audit == {"name": "support", "dismissed": 1}


async def test_a_draft_decided_twice_is_decided_once(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    generation, drafted = await world.proposals(db, org, dataset, agent, 2)
    service = CaseGenerationService(db, vector_store=MagicMock())
    await service.dismiss(owner, dataset.id, CaseProposalDismiss(ids=[drafted[0].id]))

    with pytest.raises(NotFoundError):
        await service.accept(owner, dataset.id, _accept(drafted[0].id))
    with pytest.raises(NotFoundError):
        await service.dismiss(owner, dataset.id, CaseProposalDismiss(ids=[drafted[0].id]))
    version = await service.accept(owner, dataset.id, _accept(drafted[0].id, drafted[1].id))

    assert version.changed_cases == 1
    await db.refresh(generation)
    assert (generation.accepted_count, generation.dismissed_count) == (1, 1)


async def test_an_edit_keeps_the_document_a_generated_case_came_from(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    collection = await world.collection(db, org)
    document = await world.document(db, collection, DocumentStatus.DONE, "faq.md")
    _, drafted = await world.proposals(
        db, org, dataset, agent, 1, origin=CaseOrigin.KNOWLEDGE, source_document_id=document.id
    )
    await CaseGenerationService(db, vector_store=MagicMock()).accept(
        owner, dataset.id, _accept(drafted[0].id)
    )
    (case,) = (await DatasetService(db).list_cases(owner, dataset.id)).items

    edited = await DatasetService(db).update_case(
        owner, dataset.id, case.case_id, DatasetCaseUpdate(input="Reworded")
    )

    assert (edited.source, edited.source_document_id) == ("synthetic", document.id)


async def test_only_an_editor_of_the_dataset_sees_or_decides_its_drafts(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    _, drafted = await world.proposals(db, org, dataset, agent, 1)
    viewer = await world.member(db, org, OrgRoleName.VIEWER)
    service = CaseGenerationService(db, vector_store=MagicMock())
    shared = ResourceGrant(
        organization_id=org.id,
        subject_user_id=viewer.user_id,
        resource_type="dataset",
        resource_id=dataset.id,
        level=GrantLevel.READ.value,
    )
    db.add(shared)
    await db.flush()

    assert (await DatasetService(db).read(viewer, dataset.id)).pending_proposals == 0
    with pytest.raises(NotFoundError):
        await service.list_proposals(viewer, dataset.id)
    with pytest.raises(NotFoundError):
        await service.list_generations(viewer, dataset.id)
    with pytest.raises(NotFoundError):
        await service.accept(viewer, dataset.id, _accept(drafted[0].id))
    with pytest.raises(NotFoundError):
        await service.dismiss(viewer, dataset.id, CaseProposalDismiss(ids=[drafted[0].id]))

    shared.level = GrantLevel.EDIT.value
    await db.flush()
    listing = await DatasetService(db).list_readable(viewer)
    assert [item.pending_proposals for item in listing.items] == [1]
    version = await service.accept(viewer, dataset.id, _accept(drafted[0].id))
    assert version.number == 1


async def test_another_organization_s_drafts_are_not_found(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    _, drafted = await world.proposals(db, org, dataset, agent, 1)
    stranger_org = await world.org(db, await world.user(db))
    stranger = await world.member(db, stranger_org, OrgRoleName.OWNER)
    service = CaseGenerationService(db, vector_store=MagicMock())

    for attempt in (
        service.list_proposals(stranger, dataset.id),
        service.accept(stranger, dataset.id, _accept(drafted[0].id)),
        service.dismiss(stranger, dataset.id, CaseProposalDismiss(ids=[drafted[0].id])),
    ):
        with pytest.raises(NotFoundError):
            await attempt
    other = await DatasetService(db).create(stranger, DatasetCreate(name="theirs"))
    with pytest.raises(NotFoundError):
        await service.accept(stranger, other.id, _accept(drafted[0].id))
    assert await db.scalar(select(func.count(CaseProposal.id))) == 1


async def test_a_generation_left_running_too_long_reads_as_interrupted(db) -> None:
    owner, org, agent, dataset = await _setup(db)
    stuck, _ = await world.proposals(db, org, dataset, agent, 1)
    fresh, _ = await world.proposals(db, org, dataset, agent, 1)
    stuck.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db.flush()

    listed = {
        g.id: g
        for g in (
            await CaseGenerationService(db, vector_store=MagicMock()).list_generations(
                owner, dataset.id
            )
        ).items
    }

    assert (listed[stuck.id].status, listed[stuck.id].error) == ("failed", INTERRUPTED)
    assert (listed[fresh.id].status, listed[fresh.id].error) == (
        GenerationStatus.RUNNING.value,
        None,
    )


async def test_deleting_the_conversation_takes_its_drafts_and_erasure_takes_a_person_s(
    db,
) -> None:
    owner, org, agent, dataset = await _setup(db)
    customer = await world.user(db)
    _, kept, _ = await world.asked(db, org, agent, customer, "Kept", minutes=1)
    await world.proposals(db, org, dataset, agent, 1, source_conversation_id=kept.id)
    person = await world.user(db)
    their_run, _, _ = await world.asked(db, org, agent, person, "Theirs", minutes=2)
    await world.proposals(db, org, dataset, agent, 1, source_run_id=their_run.id)
    _, deleted, _ = await world.asked(db, org, agent, customer, "Deleted", minutes=3)
    await world.proposals(db, org, dataset, agent, 1, source_conversation_id=deleted.id)

    await ConversationService(db).delete_conversation(deleted.id, organization_id=org.id)
    purged = await PersonalDataService(db).purge(person.id)

    assert purged.case_proposals == 1
    remaining = (
        await CaseGenerationService(db, vector_store=MagicMock()).list_proposals(owner, dataset.id)
    ).items
    assert [item.source_conversation_id for item in remaining] == [kept.id]
