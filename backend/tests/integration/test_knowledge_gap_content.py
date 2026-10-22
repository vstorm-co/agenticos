"""Closing a knowledge gap from its tab, against a real database.

What a person writes, or keeps of a draft, is added to the topic's knowledge
base as a document - by whoever may change that base, audited - and the topic
reads as covered until that document goes. Content that still asks for a
detail, or repeats a number or code from people's questions, is held back. The
drafter reads the agents' context files, and the questions with what
identifies people taken out; a topic is drafted unasked only once two people
asked.
"""

import uuid
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.exceptions import BadRequestError, IdentifyingContentError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.context import ContextFile
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import RAGDocument
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.schemas.knowledge_gap import KnowledgeGapContent, KnowledgeGapContentAdd, KnowledgeGapDraft
from app.services.knowledge_gaps import KnowledgeGapService
from tests.integration.test_knowledge_gaps import (
    _a_topic,
    _agent,
    _drafter,
    _embedding,
    _group,
    _knowledge_base,
    _member,
    _owner,
    _searched,
    _topics,
    _turn,
)

pytestmark = pytest.mark.anyio


class _AcceptingStore:
    """A vector store that agrees a collection exists; the upload stops at the queue."""

    async def create_collection(self, name: str) -> None:
        del name


@pytest.fixture
def uploads(tmp_path, monkeypatch) -> Iterator[MagicMock]:
    """Accept uploads without writing to permanent storage; the parse job is queued for real."""
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    storage = MagicMock()
    storage.save = AsyncMock(return_value="rag/collection/file.md")
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)
    return storage


async def _add(db, ctx: AuthContext, topic_id: uuid.UUID, content: str, *, confirm: bool = False):
    return await KnowledgeGapService(db).add_content(
        ctx,
        topic_id,
        KnowledgeGapContentAdd(
            title="Visitor parking", content=content, confirm_identifying=confirm
        ),
        vector_store=_AcceptingStore(),
    )


async def _documents(db, kb: KnowledgeBase) -> list[RAGDocument]:
    rows = await db.execute(select(RAGDocument).where(RAGDocument.knowledge_base_id == kb.id))
    return list(rows.scalars().all())


async def _audited(db, action: str) -> list[AppAdminAuditLog]:
    rows = await db.execute(select(AppAdminAuditLog).where(AppAdminAuditLog.action == action))
    return list(rows.scalars().all())


async def test_written_content_is_added_as_a_document_and_the_topic_reads_covered(
    db, uploads
) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)

    added = await _add(db, ctx, topic_id, "Visitors park on level -1, by the lifts.")

    [document] = await _documents(db, kb)
    stored = uploads.save.await_args
    assert stored.args[1] == "visitor-parking.md"
    assert stored.args[2] == b"# Visitor parking\n\nVisitors park on level -1, by the lifts.\n"
    assert (document.filetype, document.knowledge_gap_topic_id) == ("md", topic_id)
    assert document.initiated_by_user_id == ctx.user_id
    assert added.status == "covered"
    assert added.covered_by is not None
    assert (added.covered_by.id, added.covered_by.filename) == (document.id, "visitor-parking.md")
    assert added.draft is not None and added.draft.content.startswith("Visitors park")
    [entry] = await _audited(db, "knowledge_gap.content_added")
    assert entry.target_id == str(topic_id)
    assert entry.details["document_id"] == str(document.id)
    assert entry.details["confirmed_identifying"] is False
    service = KnowledgeGapService(db)
    assert (await service.list_for_knowledge_base(ctx, kb.id, status="open")).total == 0
    assert (await service.list_for_knowledge_base(ctx, kb.id, status="covered")).total == 1


async def test_a_topic_whose_document_is_deleted_reads_open_again(db, uploads) -> None:
    del uploads
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    await _add(db, ctx, topic_id, "Visitors park on level -1.")

    await db.execute(delete(RAGDocument).where(RAGDocument.knowledge_base_id == kb.id))
    await db.flush()
    db.expire_all()
    service = KnowledgeGapService(db)
    detail = await service.read(ctx, topic_id)

    assert (detail.status, detail.covered_by) == ("open", None)
    assert (await service.list_for_knowledge_base(ctx, kb.id, status="open")).total == 1
    assert (await service.list_for_knowledge_base(ctx, kb.id, status="covered")).total == 0


async def test_reopening_a_covered_topic_leaves_its_document_in_the_knowledge_base(
    db, uploads
) -> None:
    del uploads
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    await _add(db, ctx, topic_id, "Visitors park on level -1.")

    reopened = await KnowledgeGapService(db).set_status(ctx, topic_id, "open")

    assert (reopened.status, reopened.covered_by) == ("open", None)
    assert len(await _documents(db, kb)) == 1


@pytest.mark.security
async def test_adding_content_takes_edit_access_to_the_knowledge_base(db, uploads) -> None:
    del uploads
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)

    with pytest.raises(NotFoundError):
        await _add(db, operator, topic_id, "Visitors park on level -1.")
    with pytest.raises(NotFoundError):
        await KnowledgeGapService(db).save_content(
            operator, topic_id, KnowledgeGapContent(title="Parking", content="Level -1.")
        )
    assert await _documents(db, kb) == []

    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=operator.user_id,
            resource_type="collection",
            resource_id=kb.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    added = await _add(db, operator, topic_id, "Visitors park on level -1.")

    assert added.status == "covered"
    assert [d.initiated_by_user_id for d in await _documents(db, kb)] == [operator.user_id]


@pytest.mark.security
async def test_another_organizations_topic_cannot_be_written_or_added(db, uploads) -> None:
    del uploads
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)
    stranger = await _owner(db)

    with pytest.raises(NotFoundError):
        await _add(db, stranger, topic_id, "Visitors park on level -1.")
    assert await _documents(db, kb) == []


async def test_content_repeating_an_order_number_is_held_until_somebody_confirms_it(
    db, uploads
) -> None:
    del uploads
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    run, _ = await _turn(db, ctx, await _agent(db, ctx), question="Where is my order 7781?")
    await _searched(db, ctx, run, kb, query="parking order")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)

    with pytest.raises(IdentifyingContentError) as refused:
        await _add(db, ctx, topic_id, "Order 7781 was parked on level -1. Mail ann@example.com")
    assert await _documents(db, kb) == []
    added = await _add(
        db, ctx, topic_id, "Order 7781 was parked on level -1. Mail ann@example.com", confirm=True
    )

    flags = refused.value.details["flags"]
    assert {"kind": "shared", "value": "7781", "count": 1} in flags
    assert {"kind": "personal_data", "value": "email", "count": 1} in flags
    assert added.status == "covered"
    [entry] = await _audited(db, "knowledge_gap.content_added")
    assert entry.details["confirmed_identifying"] is True
    assert "7781" not in str(entry.details)


async def test_a_policy_figure_is_not_flagged_and_what_a_person_writes_is_not_redacted(
    db,
) -> None:
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)

    saved = await KnowledgeGapService(db).save_content(
        ctx,
        topic_id,
        KnowledgeGapContent(
            title="Refunds",
            content="Refunds within 30 days; above $500 a manager approves. Ticket 4321.",
        ),
    )

    assert saved.draft is not None
    assert saved.draft.content.endswith("above $500 a manager approves. Ticket 4321.")
    assert saved.draft.flags == []
    assert saved.status == "open"
    assert await _documents(db, kb) == []


async def test_content_still_asking_for_a_detail_is_refused(db, uploads) -> None:
    del uploads
    ctx = await _owner(db)
    kb, _, topic_id = await _a_topic(db, ctx)

    saved = await KnowledgeGapService(db).save_content(
        ctx,
        topic_id,
        KnowledgeGapContent(title="Parking", content="Visitors park on level {{parking level}}."),
    )
    with pytest.raises(BadRequestError) as refused:
        await _add(db, ctx, topic_id, "Visitors park on level {{parking level}}.")

    assert saved.draft is not None and saved.draft.blanks == ["parking level"]
    assert refused.value.details["fields"][0]["field"] == "content"
    assert await _documents(db, kb) == []


async def _context_file(db, ctx: AuthContext, name: str, content: str) -> ContextFile:
    file = ContextFile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name=name,
        content=content,
    )
    db.add(file)
    await db.flush()
    return file


async def _published(db, ctx: AuthContext, agent: Agent, *files: ContextFile) -> None:
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        organization_id=ctx.organization_id,
        version=1,
        spec={"name": agent.name, "context_ids": [str(file.id) for file in files]},
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()


async def test_the_drafter_reads_the_agents_context_files_and_no_identifying_detail(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    policy = await _context_file(
        db, ctx, "refund-policy", "Digital goods are not refundable once downloaded."
    )
    await _published(db, ctx, agent, policy)
    run, _ = await _turn(
        db, ctx, agent, question="Refund e-book order 7781? Mail me at ann@example.com"
    )
    await _searched(db, ctx, run, kb, query="parking refund")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    drafting_run, _ = await _turn(db, ctx, agent)

    with _drafter(
        KnowledgeGapDraft(
            title="E-book refunds",
            content="Covered by refund-policy: downloaded e-books are not refunded.",
            context_files=[1, 3],
            already_covered=True,
        ),
        drafting_run,
    ) as run_it:
        drafted = await KnowledgeGapService(db).draft(ctx, topic_id)

    prompt = run_it.await_args.kwargs["prompt"]
    assert "### Context file 1: refund-policy" in prompt
    assert "Digital goods are not refundable once downloaded." in prompt
    assert "7781" not in prompt and "ann@example.com" not in prompt
    assert "Refund e-book order [number]? Mail me at [redacted:email]" in prompt
    assert drafted.draft is not None
    assert drafted.draft.already_covered
    assert [(s.kind, s.label) for s in drafted.draft.sources] == [("context", "refund-policy")]
    assert drafted.draft.unverified == 1


async def _one_asker_topic(db, ctx: AuthContext, kb: KnowledgeBase, agent: Agent) -> uuid.UUID:
    for question in ("Where can visitors park?", "Is there visitor parking?"):
        run, _ = await _turn(db, ctx, agent, question=question)
        await _searched(db, ctx, run, kb, query=f"visitor parking {question}")
    with _embedding():
        await _group(db, ctx, kb)
    [topic_id] = await _topics(db, kb)
    return topic_id


async def test_a_topic_one_person_asked_is_not_drafted_unasked_and_two_people_are_enough(
    db,
) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    topic_id = await _one_asker_topic(db, ctx, kb, agent)
    service = KnowledgeGapService(db)
    drafting_run, _ = await _turn(db, ctx, agent)

    with pytest.raises(BadRequestError) as refused:
        await service.draft(ctx, topic_id, automatic=True)
    other = await _member(db, ctx, OrgRoleName.ADMIN)
    run, _ = await _turn(db, other, agent, question="Visitor parking, anyone?")
    await _searched(db, other, run, kb, query="visitor parking again")
    with _embedding():
        await _group(db, ctx, kb)
    with _drafter(
        KnowledgeGapDraft(title="Parking", content="Visitors park on level {{level}}."),
        drafting_run,
    ):
        drafted = await service.draft(ctx, topic_id, automatic=True)

    assert refused.value.details["askers"] == 1
    assert drafted.asker_count == 2
    assert drafted.draft is not None and drafted.draft.blanks == ["level"]


async def test_runs_with_nobody_behind_them_count_as_one_asker(db) -> None:
    ctx = await _owner(db)
    kb = await _knowledge_base(db, ctx)
    agent = await _agent(db, ctx)
    topic_id = await _one_asker_topic(db, ctx, kb, agent)
    nobody = AuthContext(user_id=None, organization_id=ctx.organization_id, role="owner")
    for query in ("visitor parking first", "visitor parking second"):
        run = AgentRun(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            status="completed",
        )
        db.add(run)
        await db.flush()
        await _searched(db, nobody, run, kb, query=query)
    with _embedding():
        await _group(db, ctx, kb)

    [topic] = (await KnowledgeGapService(db).list_for_knowledge_base(ctx, kb.id)).items

    assert topic.id == topic_id
    assert (topic.question_count, topic.asker_count) == (4, 2)
