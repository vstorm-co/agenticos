"""Maintenance edits only consented Notes and leaves an undoable history."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.conversation import Conversation, Message
from app.db.models.memory import AgentMemoryFile, MemoryNoteRevision
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import memory_repo
from app.schemas.memory import MemoryNoteAutoUpdate, MemoryNoteEdit, MemoryNoteRestore
from app.services.memory import MemoryService, extraction

pytestmark = [pytest.mark.anyio, pytest.mark.security]

QUOTE = "Use the rollout checklist at the next handoff."


@dataclass(frozen=True)
class World:
    owner: AuthContext
    agent_id: UUID
    version_id: UUID
    note: AgentMemoryFile


async def world(db: AsyncSession) -> World:
    user = User(email=f"{uuid4()}@example.test")
    db.add(user)
    await db.flush()
    org = Organization(name="Atlas", slug=f"atlas-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(name="Helper", slug="helper", organization_id=org.id)
    db.add_all([agent, OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")])
    await db.flush()
    version = AgentVersion(
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec={"capabilities": [{"id": "memory_files"}]},
    )
    db.add(version)
    note = await memory_repo.create(
        db,
        organization_id=org.id,
        agent_id=agent.id,
        owner_key=person_owner_key(user.id),
        name="rollout",
        description=None,
        content="Initial content",
        content_format="md",
        kind="note",
    )
    await db.commit()
    return World(
        AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER),
        agent.id,
        version.id,
        note,
    )


async def session(
    db: AsyncSession, data: World, *, at: datetime, content: str = QUOTE
) -> tuple[UUID, UUID]:
    ctx = data.owner
    conversation = Conversation(user_id=ctx.subject_id, organization_id=ctx.organization_id)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        agent_id=data.agent_id,
        agent_version_id=data.version_id,
        conversation_id=conversation.id,
        status=RunStatus.COMPLETED.value,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    message = Message(
        conversation_id=conversation.id, role="user", content=content, created_at=at, run_id=run.id
    )
    db.add(message)
    await db.commit()
    return run.id, message.id


async def test_note_overwrite_requires_consent_and_restores_the_prior_body(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    svc = MemoryService(db)
    note = data.note
    now = datetime.now(UTC)
    run, _ = await session(db, data, at=now - timedelta(days=1))
    seen: list[list[dict[str, str]]] = []

    async def think(_self, _ctx, *, prompt, output_type, **_kwargs):
        seen.append(json.loads(prompt)["notes"])
        return output_type.model_validate(
            {
                "note": {
                    "action": "update",
                    "name": note.name,
                    "content": "New checklist",
                    "evidence": QUOTE,
                }
            }
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    await extraction.extract(db, data.owner.organization_id, run)
    assert seen == [[]]
    assert note.content == "Initial content"
    assert not note.auto_update

    enabled = await svc.set_note_auto_update(
        data.owner, note.id, MemoryNoteAutoUpdate(enabled=True, expected_updated_at=note.updated_at)
    )
    assert enabled.auto_update is True
    await db.commit()
    newer, source = await session(db, data, at=datetime.now(UTC))
    await extraction.extract(db, data.owner.organization_id, newer)
    assert seen[-1] == [{"name": note.name, "content": "Initial content"}]
    assert note.content == "New checklist"
    assert note.maintenance_source_message_id == source

    await extraction.extract(db, data.owner.organization_id, newer)
    page = await svc.note_revisions(data.owner, note.id, skip=0, limit=5)
    assert page.total == 1
    assert page.items[0].content == "Initial content"
    assert page.items[0].changed_by == "maintenance"
    restored = await svc.restore_note_revision(
        data.owner,
        note.id,
        page.items[0].id,
        MemoryNoteRestore(expected_updated_at=note.updated_at),
    )
    assert restored.content == "Initial content"
    await db.commit()
    await extraction.extract(db, data.owner.organization_id, run)
    assert note.content == "Initial content"
    revisions = await svc.note_revisions(data.owner, note.id, skip=0, limit=5)
    assert [row.content for row in revisions.items] == ["New checklist", "Initial content"]

    outsider = AuthContext(
        user_id=uuid4(), organization_id=data.owner.organization_id, role=OrgRoleName.OWNER
    )
    with pytest.raises(NotFoundError):
        await svc.note_revisions(outsider, note.id, skip=0, limit=5)
    with pytest.raises(ConflictError):
        await svc.restore_note_revision(
            data.owner, note.id, page.items[0].id, MemoryNoteRestore(expected_updated_at=None)
        )
    with pytest.raises(NotFoundError):
        await svc.restore_note_revision(
            data.owner, note.id, uuid4(), MemoryNoteRestore(expected_updated_at=note.updated_at)
        )
    await svc.delete_note(data.owner, note.id)
    assert not (await db.scalars(select(MemoryNoteRevision.id))).all()


async def test_maintenance_does_not_overwrite_a_change_during_the_model_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    svc = MemoryService(db)
    note = data.note
    await svc.set_note_auto_update(
        data.owner, note.id, MemoryNoteAutoUpdate(enabled=True, expected_updated_at=note.updated_at)
    )
    await db.commit()
    run, _ = await session(db, data, at=datetime.now(UTC))

    async def think(_self, _ctx, *, output_type, **_kwargs):
        await svc.edit_note(
            data.owner,
            note.id,
            MemoryNoteEdit(content="Human correction", expected_updated_at=note.updated_at),
        )
        await db.commit()
        return output_type.model_validate(
            {
                "note": {
                    "action": "update",
                    "name": note.name,
                    "content": "Obsolete version",
                    "evidence": QUOTE,
                }
            }
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    await extraction.extract(db, data.owner.organization_id, run)
    assert note.content == "Human correction"
    page = await svc.note_revisions(data.owner, note.id, skip=0, limit=5)
    assert [row.changed_by for row in page.items] == ["person"]


async def test_maintenance_can_create_a_private_note_and_cannot_replace_a_name_on_create(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    run, source = await session(db, data, at=datetime.now(UTC))
    name = "handoff-checklist"
    quote = "Only the assistant said this."

    async def think(_self, _ctx, *, output_type, **_kwargs):
        return output_type.model_validate(
            {"note": {"action": "create", "name": name, "content": "New note", "evidence": quote}}
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    await extraction.extract(db, data.owner.organization_id, run)
    assert await db.scalar(select(AgentMemoryFile).where(AgentMemoryFile.name == name)) is None
    quote = QUOTE
    await extraction.extract(db, data.owner.organization_id, run)
    await extraction.extract(db, data.owner.organization_id, run)
    note = (await db.scalars(select(AgentMemoryFile).where(AgentMemoryFile.name == name))).one()
    assert note.content == "New note"
    assert note.maintenance_source_message_id == source
    assert note.auto_update
    name = data.note.name
    await extraction.extract(db, data.owner.organization_id, run)
    assert data.note.content == "Initial content"


async def test_a_linked_note_only_accepts_objects_from_the_same_owner_store(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.repositories.memory_claim import ClaimScope
    from app.schemas.memory import MemoryObjectRef
    from app.services.memory import NoteObjectUnavailable, _native, claims

    data = await world(db)
    other = await world(db)
    owner_key = person_owner_key(data.owner.subject_id)

    async def save_object(source: World) -> UUID:
        save = await claims.remember(
            db,
            organization_id=source.owner.organization_id,
            scope=ClaimScope(person_owner_key(source.owner.subject_id)),
            statement="Atlas uses a private handoff.",
            subject="handoff",
            kind="fact",
            origin="person",
            conversation_id=None,
            run_id=None,
            object_ref=MemoryObjectRef(kind="company", name="Atlas"),
        )
        assert save.claim.object_id is not None
        return save.claim.object_id

    owned = await save_object(data)
    hidden = await save_object(other)
    await db.commit()

    @asynccontextmanager
    async def use_db():
        yield db

    monkeypatch.setattr(_native, "get_db_context", use_db)

    async def create(object_id: UUID) -> bool:
        return await _native.write_file(
            organization_id=data.owner.organization_id,
            agent_id=data.agent_id,
            owner_key=owner_key,
            name="atlas-handoff",
            content="Checklist",
            description=None,
            kind="note",
            run_id=None,
            object_id=object_id,
        )

    with pytest.raises(NoteObjectUnavailable):
        await create(hidden)
    assert await create(owned)
    page = await MemoryService(db).mine(data.owner, skip=0, limit=5)
    note = next(item for item in page.items if item.name == "atlas-handoff")
    assert note.object_id == owned


async def test_maintenance_respects_an_opt_out_during_the_model_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    svc = MemoryService(db)
    note = data.note
    await svc.set_note_auto_update(
        data.owner, note.id, MemoryNoteAutoUpdate(enabled=True, expected_updated_at=note.updated_at)
    )
    await db.commit()
    run, _ = await session(db, data, at=datetime.now(UTC))

    async def think(_self, _ctx, *, output_type, **_kwargs):
        await svc.set_note_auto_update(
            data.owner,
            note.id,
            MemoryNoteAutoUpdate(enabled=False, expected_updated_at=note.updated_at),
        )
        await db.commit()
        return output_type.model_validate(
            {
                "note": {
                    "action": "update",
                    "name": note.name,
                    "content": "No consent",
                    "evidence": QUOTE,
                }
            }
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    await extraction.extract(db, data.owner.organization_id, run)
    assert note.content == "Initial content"
    assert not note.auto_update


async def test_existing_automatic_note_cannot_be_blindly_overwritten_by_an_agent(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.services.memory import NoteChangedDuringRead, _native

    data = await world(db)
    note = data.note
    await MemoryService(db).set_note_auto_update(
        data.owner, note.id, MemoryNoteAutoUpdate(enabled=True, expected_updated_at=note.updated_at)
    )
    await db.commit()

    @asynccontextmanager
    async def use_db():
        yield db

    monkeypatch.setattr(_native, "get_db_context", use_db)
    with pytest.raises(NoteChangedDuringRead):
        await _native.edit_file(
            organization_id=data.owner.organization_id,
            agent_id=data.agent_id,
            owner_key=person_owner_key(data.owner.subject_id),
            name=note.name,
            content="Blind edit",
            run_id=None,
        )
    assert note.content == "Initial content"


async def test_an_older_relevant_note_is_considered_before_newer_unrelated_notes(
    db: AsyncSession,
) -> None:
    data = await world(db)
    owner_key = person_owner_key(data.owner.subject_id)
    note = data.note
    note.auto_update = True
    note.written_at = datetime.now(UTC) - timedelta(days=10)
    for suffix in range(5):
        await memory_repo.create(
            db,
            organization_id=data.owner.organization_id,
            agent_id=data.agent_id,
            owner_key=owner_key,
            name=f"unrelated-{suffix}",
            description=None,
            content="Design reference",
            content_format="md",
            kind="note",
            auto_update=True,
        )
    selected = await memory_repo.automatic_notes(
        db,
        organization_id=data.owner.organization_id,
        agent_id=data.agent_id,
        owner_key=owner_key,
        terms=["rollout", "checklist"],
        max_chars=4000,
        limit=1,
    )
    assert [item.id for item in selected] == [note.id]


async def test_one_session_can_record_the_same_property_on_distinct_projects(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    quote = "Anna owns Atlas. Piotr owns Boreal."
    run, _ = await session(db, data, at=datetime.now(UTC), content=quote)

    async def think(_self, _ctx, *, output_type, **_kwargs):
        return output_type.model_validate(
            {
                "claims": [
                    {
                        "statement": sentence,
                        "subject": "owner",
                        "evidence": sentence,
                        "object_ref": {"kind": "project", "name": project},
                    }
                    for sentence, project in [
                        ("Anna owns Atlas.", "Atlas"),
                        ("Piotr owns Boreal.", "Boreal"),
                    ]
                ]
            }
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    assert await extraction.extract(db, data.owner.organization_id, run) == 2
    page = await MemoryService(db).my_claims(data.owner, skip=0, limit=10, history=False)
    assert {claim.statement for claim in page.items} == {"Anna owns Atlas.", "Piotr owns Boreal."}
    assert len({claim.object_id for claim in page.items} - {None}) == 2


async def test_note_consent_rejects_stale_revisions_and_oversized_bodies(db: AsyncSession) -> None:
    data = await world(db)
    svc = MemoryService(db)
    note = data.note

    with pytest.raises(ConflictError, match="note changed"):
        await svc.set_note_auto_update(
            data.owner,
            note.id,
            MemoryNoteAutoUpdate(enabled=True, expected_updated_at=datetime.now(UTC)),
        )
    note.content = "x" * 4001
    await db.flush()
    await db.refresh(note)
    revision = note.updated_at
    with pytest.raises(ConflictError, match="at most 4000 characters"):
        await svc.set_note_auto_update(
            data.owner,
            note.id,
            MemoryNoteAutoUpdate(enabled=True, expected_updated_at=revision),
        )

    # A retry of the current setting does not modify the consent revision.
    again = await svc.set_note_auto_update(
        data.owner,
        note.id,
        MemoryNoteAutoUpdate(enabled=False, expected_updated_at=revision),
    )
    assert again.updated_at == revision and not again.auto_update


async def test_blank_maintenance_output_does_not_create_or_version_notes(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = await world(db)
    run, _ = await session(db, data, at=datetime.now(UTC))

    async def think(_self, _ctx, *, output_type, **_kwargs):
        return output_type.model_validate(
            {"note": {"action": "create", "name": "blank", "content": "  ", "evidence": QUOTE}}
        )

    monkeypatch.setattr(extraction.ProactiveThinker, "think", think)
    await extraction.extract(db, data.owner.organization_id, run)
    listing = await MemoryService(db).mine(data.owner, skip=0, limit=10)
    assert [note.name for note in listing.items] == ["rollout"]
    assert await db.scalar(select(MemoryNoteRevision.id)) is None


async def test_unchanged_note_has_no_new_revision_and_candidates_can_be_unranked(
    db: AsyncSession,
) -> None:
    data = await world(db)
    note = data.note
    await memory_repo.replace_content(db, file=note, content=note.content, changed_by="person")
    assert await db.scalar(select(MemoryNoteRevision.id)) is None
    note.auto_update = True
    await db.flush()
    candidates = await memory_repo.automatic_notes(
        db,
        organization_id=data.owner.organization_id,
        agent_id=data.agent_id,
        owner_key=person_owner_key(data.owner.subject_id),
        terms=[],
        max_chars=4000,
        limit=4,
    )
    assert [row.id for row in candidates] == [note.id]
