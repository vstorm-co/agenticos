"""A small organization for the case-generation integration tests to stand on.

Shared by the tests of what the generator reads and of what it drafts, which
need the same people, agents, conversations and collections.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.case_generation import CaseGeneration, CaseOrigin, CaseProposal
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import Dataset
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.user import User
from app.repositories import case_generation_repo
from app.schemas.dataset import DatasetRead

START = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


async def user(db) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def org(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    return org


async def agent(
    db, org: Organization, *, draft_spec: dict | None = None, visibility: str = "private"
) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=org.id,
        slug=f"clerk-{uuid.uuid4().hex[:8]}",
        name="Clerk",
        draft_spec=draft_spec or {},
        visibility=visibility,
    )
    db.add(agent)
    await db.flush()
    return agent


async def asked(
    db,
    org: Organization,
    agent: Agent,
    person: User,
    question: str,
    *,
    minutes: int,
    rating: int | None = None,
    comment: str | None = None,
) -> tuple[AgentRun, Conversation, Message]:
    """A conversation in which `person` asked `agent` one question and got an answer."""
    conversation = Conversation(
        id=uuid.uuid4(), user_id=person.id, organization_id=org.id, title="Support"
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        user_id=person.id,
        conversation_id=conversation.id,
        status="completed",
        started_at=START + timedelta(minutes=minutes),
    )
    db.add(run)
    await db.flush()
    asked = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=run.id,
        role="user",
        content=question,
        created_at=START + timedelta(minutes=minutes),
    )
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        run_id=run.id,
        agent_id=agent.id,
        role="assistant",
        content="An answer.",
        created_at=START + timedelta(minutes=minutes, seconds=5),
    )
    db.add_all([asked, answer])
    await db.flush()
    if rating is not None:
        db.add(
            MessageRating(message_id=answer.id, user_id=person.id, rating=rating, comment=comment)
        )
        await db.flush()
    return run, conversation, asked


async def collection(
    db, org: Organization | None, *, visibility: str = "org", owner: User | None = None
) -> KnowledgeBase:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=f"Docs {uuid.uuid4().hex[:6]}",
        scope=KBScope.ORG.value if org else KBScope.PERSONAL.value,
        organization_id=org.id if org else None,
        collection_name=f"c_{uuid.uuid4().hex[:12]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        visibility=visibility,
        owner_user_id=owner.id if owner else None,
    )
    db.add(kb)
    await db.flush()
    return kb


async def document(
    db, kb: KnowledgeBase, status: DocumentStatus, name: str, *, vector_id: str | None = None
) -> RAGDocument:
    document = RAGDocument(
        id=uuid.uuid4(),
        collection_name=kb.collection_name,
        filename=name,
        filesize=4,
        filetype="md",
        storage_path="",
        status=status,
        chunk_count=3,
        ingestion_config={},
        knowledge_base_id=kb.id,
        vector_document_id=vector_id,
    )
    db.add(document)
    await db.flush()
    return document


async def dataset(db, org: Organization) -> Dataset:
    dataset = Dataset(id=uuid.uuid4(), organization_id=org.id, name=f"d-{uuid.uuid4().hex[:6]}")
    db.add(dataset)
    await db.flush()
    return dataset


async def proposals(
    db,
    org: Organization,
    dataset: Dataset | DatasetRead,
    agent: Agent,
    count: int,
    *,
    origin: CaseOrigin = CaseOrigin.CONVERSATION,
    **fields: object,
) -> tuple[CaseGeneration, list[CaseProposal]]:
    """A generation that drafted `count` proposals, `question 0` onwards, all with `fields`."""
    generation = await case_generation_repo.create_generation(
        db,
        organization_id=org.id,
        dataset_id=dataset.id,
        agent_id=agent.id,
        requested_by_user_id=None,
        sources=[origin.value],
        requested_count=count,
    )
    proposals = [
        CaseProposal(
            id=uuid.uuid4(),
            organization_id=org.id,
            generation_id=generation.id,
            dataset_id=dataset.id,
            position=index,
            origin=origin.value,
            input=f"question {index}",
            **fields,
        )
        for index in range(count)
    ]
    await case_generation_repo.add_proposals(db, proposals)
    return generation, proposals


async def member(
    db, org: Organization, role: OrgRoleName, person: User | None = None
) -> AuthContext:
    """`person` (a new one by default) holding `role` in `org`, as a caller."""
    person = person or await user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=org.id, user_id=person.id, role=role.value
        )
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=role.value)


async def publish(db, agent_row: Agent, spec: dict) -> AgentVersion:
    """Publish `spec` as the agent's current version."""
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent_row.id,
        organization_id=agent_row.organization_id,
        version=1,
        spec=spec,
    )
    db.add(version)
    await db.flush()
    agent_row.current_version_id = version.id
    await db.flush()
    return version
