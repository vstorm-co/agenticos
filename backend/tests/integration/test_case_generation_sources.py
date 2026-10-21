"""What the case generator is shown, and what it is refused, against Postgres.

The claims a mocked session cannot make:

- the agent is described by its published spec, with each tool under the name
  this agent's binding gives it - the name a case's expected call must match -
  and only the skills the caller may view;
- knowledge passages come only from the collections the caller may read, spread
  across documents and read under the collection's own tenant, with the
  collections the caller could not read counted rather than hidden;
- conversations need `runs:view`, and a credential in one never reaches the model;
- a source with nothing to draft from, or one the caller may not use, is refused
  by name.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.case_generation import CaseOrigin
from app.db.models.rag_document import DocumentStatus
from app.db.models.skill import Skill
from app.services.case_generation.sources import PASSAGES_PER_DOCUMENT, SourceGatherer
from app.services.rag.models import DocumentChunk
from tests.integration import case_generation_world as world

pytestmark = pytest.mark.anyio

_KEY = "ghp_" + "b" * 36


class _Chunks:
    """A vector store that answers chunk reads, and remembers under which tenant."""

    def __init__(self, chunks: dict[str, list[str]]) -> None:
        self.chunks = chunks
        self.tenants: list[uuid.UUID | None] = []

    async def get_document_chunks(
        self, collection_name: str, document_id: str, tenant: uuid.UUID | None = None
    ) -> list[DocumentChunk]:
        del collection_name
        self.tenants.append(tenant)
        return [
            DocumentChunk(content=text, page_num=index, chunk_num=index)
            for index, text in enumerate(self.chunks.get(document_id, []), start=1)
        ]


def _gatherer(db, chunks: dict[str, list[str]] | None = None) -> SourceGatherer:
    return SourceGatherer(db, _Chunks(chunks or {}))  # ty: ignore[invalid-argument-type]


async def _owner(db):
    person = await world.user(db)
    org = await world.org(db, person)
    return await world.member(db, org, OrgRoleName.OWNER, person), org


def _refusal(exc: pytest.ExceptionInfo[BadRequestError]) -> str:
    (problem,) = exc.value.details["fields"]
    assert problem["field"] == "sources"
    return problem["message"]


async def test_the_agent_is_described_by_its_published_spec_and_its_own_tool_names(db) -> None:
    owner, org = await _owner(db)
    db.add(
        Skill(
            organization_id=org.id,
            name="refunds",
            description="The refund policy",
            content="Refunds within 30 days." + "x" * 5000,
            visibility="org",
        )
    )
    await db.flush()
    skill_id = (await db.execute(Skill.__table__.select())).first().id
    agent = await world.agent(db, org, draft_spec={"name": "Draft", "instructions": "draft only"})
    await world.publish(
        db,
        agent,
        {
            "name": "Clerk",
            "instructions": "Answer about orders.",
            "skill_ids": [str(skill_id)],
            "capabilities": [
                {
                    "id": "knowledge",
                    "tool_overrides": {"search_documents": {"name": "search_handbook"}},
                },
                {"id": "no_such_capability_here"},
                {"id": "charts", "enabled": False},
                {"id": "artifacts"},
            ],
        },
    )

    material = await _gatherer(db).gather(owner, agent.id, [CaseOrigin.AGENT])

    assert material.agent.instructions == "Answer about orders."
    assert [(tool.name, tool.writes) for tool in material.agent.tools] == [
        ("search_handbook", False),
        ("publish_artifact", True),
        ("read_artifact", False),
    ]
    (skill,) = material.agent.skills
    assert skill.name == "refunds"
    assert skill.body.endswith("[...]")
    assert len(skill.body) < 2100


@pytest.mark.security
async def test_only_the_skills_the_caller_may_view_are_quoted(db) -> None:
    """Viewing an agent is not reading the private skills it was published with."""
    owner, org = await _owner(db)
    member = await world.member(db, org, OrgRoleName.MEMBER)
    skills = [
        Skill(
            organization_id=org.id,
            owner_user_id=owner.user_id,
            name=name,
            description=name,
            content=f"{name} body",
            visibility=visibility,
        )
        for name, visibility in (("private-playbook", "private"), ("refunds", "org"))
    ]
    db.add_all(skills)
    await db.flush()
    agent = await world.agent(
        db,
        org,
        visibility="org",
        draft_spec={
            "name": "Clerk",
            "instructions": "Answer.",
            "skill_ids": [str(skill.id) for skill in skills],
        },
    )

    seen = await _gatherer(db).gather(member, agent.id, [CaseOrigin.AGENT])
    everything = await _gatherer(db).gather(owner, agent.id, [CaseOrigin.AGENT])

    assert [skill.name for skill in seen.agent.skills] == ["refunds"]
    assert [skill.name for skill in everything.agent.skills] == ["private-playbook", "refunds"]


async def test_an_unpublished_agent_is_described_by_its_draft_or_refused(db) -> None:
    owner, org = await _owner(db)
    drafted = await world.agent(db, org, draft_spec={"name": "Clerk", "instructions": "Be kind."})
    unfinished = await world.agent(db, org)

    material = await _gatherer(db).gather(owner, drafted.id, [CaseOrigin.RED_TEAM])

    assert material.agent.instructions == "Be kind."
    with pytest.raises(BadRequestError) as refused:
        await _gatherer(db).gather(owner, unfinished.id, [CaseOrigin.AGENT])
    assert refused.value.details["fields"][0]["field"] == "agent_id"


async def test_an_agent_the_caller_may_not_view_is_not_found(db) -> None:
    owner, org = await _owner(db)
    private = await world.agent(db, org, draft_spec={"name": "Secret"})
    member = await world.member(db, org, OrgRoleName.MEMBER)
    stranger, _ = await _owner(db)

    for caller in (member, stranger):
        with pytest.raises(NotFoundError):
            await _gatherer(db).gather(caller, private.id, [CaseOrigin.AGENT])
    del owner


async def test_knowledge_passages_come_from_readable_collections_spread_and_redacted(db) -> None:
    owner, org = await _owner(db)
    member = await world.member(db, org, OrgRoleName.MEMBER)
    readable = await world.collection(db, org)
    hidden = await world.collection(db, org, visibility="private", owner=await world.user(db))
    foreign = await world.collection(db, await world.org(db, await world.user(db)))
    handbook = await world.document(
        db, readable, DocumentStatus.DONE, "handbook.md", vector_id="v1"
    )
    await world.document(db, readable, DocumentStatus.DONE, "unindexed.md")
    await world.document(db, hidden, DocumentStatus.DONE, "salaries.md", vector_id="v2")
    agent = await world.agent(
        db,
        org,
        visibility="org",
        draft_spec={
            "name": "Clerk",
            "collection_ids": [str(readable.id), str(hidden.id), str(foreign.id)],
        },
    )
    store = _Chunks(
        {
            "v1": ["Returns: 30 days.", "  ", f"Token {_KEY}", "Shipping: 2 days.", "Last."],
            "v2": ["Salaries."],
        }
    )

    material = await SourceGatherer(db, store).gather(  # ty: ignore[invalid-argument-type]
        member, agent.id, [CaseOrigin.KNOWLEDGE]
    )

    assert {p.document_id for p in material.passages} == {handbook.id}
    assert len(material.passages) == PASSAGES_PER_DOCUMENT
    assert [p.ref for p in material.passages] == ["P1", "P2", "P3"]
    assert material.passages[0].text == "Returns: 30 days."
    assert material.passages[-1].text == "Last."
    assert all(_KEY not in p.text for p in material.passages)
    assert material.excluded_collections == 1
    assert store.tenants == [readable.vector_tenant]
    del owner


async def test_knowledge_with_nothing_to_draft_from_is_refused_by_name(db) -> None:
    owner, org = await _owner(db)
    member = await world.member(db, org, OrgRoleName.MEMBER)
    bare = await world.agent(db, org, draft_spec={"name": "Bare"})
    hidden = await world.collection(db, org, visibility="private", owner=await world.user(db))
    empty = await world.collection(db, org)
    await world.document(db, empty, DocumentStatus.DONE, "blank.md", vector_id="v0")
    behind = await world.agent(
        db, org, visibility="org", draft_spec={"name": "B", "collection_ids": [str(hidden.id)]}
    )
    blank = await world.agent(db, org, draft_spec={"name": "C", "collection_ids": [str(empty.id)]})

    with pytest.raises(BadRequestError) as no_collection:
        await _gatherer(db).gather(owner, bare.id, [CaseOrigin.KNOWLEDGE])
    with pytest.raises(BadRequestError) as unreadable:
        await _gatherer(db).gather(member, behind.id, [CaseOrigin.KNOWLEDGE])
    with pytest.raises(BadRequestError) as nothing_indexed:
        await _gatherer(db, {"v0": ["", " "]}).gather(owner, blank.id, [CaseOrigin.KNOWLEDGE])

    assert "no knowledge base" in _refusal(no_collection)
    assert "cannot read" in _refusal(unreadable)
    assert "no indexed text" in _refusal(nothing_indexed)


async def test_conversations_need_runs_view_and_reach_the_model_redacted(db) -> None:
    owner, org = await _owner(db)
    agent = await world.agent(db, org, visibility="org", draft_spec={"name": "Clerk"})
    customer = await world.user(db)
    await world.asked(db, org, agent, customer, "How do I reset?", minutes=1)
    await world.asked(
        db,
        org,
        agent,
        customer,
        f"My key {_KEY} fails",
        minutes=2,
        rating=-1,
        comment=f"It printed {_KEY} back",
    )
    member = await world.member(db, org, OrgRoleName.MEMBER)
    silent = await world.agent(db, org, draft_spec={"name": "New"})

    material = await _gatherer(db).gather(owner, agent.id, [CaseOrigin.CONVERSATION])

    disliked, plain = material.questions
    assert (disliked.ref, plain.ref) == ("C1", "C2")
    assert disliked.rated_down and not plain.rated_down
    assert _KEY not in disliked.text
    assert disliked.comment is not None
    assert _KEY not in disliked.comment
    assert plain.comment is None
    with pytest.raises(BadRequestError) as no_runs_view:
        await _gatherer(db).gather(member, agent.id, [CaseOrigin.CONVERSATION])
    with pytest.raises(BadRequestError) as nobody_asked:
        await _gatherer(db).gather(owner, silent.id, [CaseOrigin.CONVERSATION])
    assert "view runs" in _refusal(no_runs_view)
    assert "Nobody has asked" in _refusal(nobody_asked)
