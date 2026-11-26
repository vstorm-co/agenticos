"""Company/personal memory replay on the real ledger and queue."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.memory_keys import organization_owner_key, person_owner_key
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.group import Group, GroupMember
from app.db.models.mcp_connection import McpConnection
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import MemoryMailEvent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import suggestion_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.memory import (
    MemoryClaimCorrect,
    MemoryClaimShare,
    MemoryMailConfig,
    MemoryNoteShare,
    MemoryObjectRef,
)
from app.services.memory import MemoryService, claims
from app.services.memory.mail import MemoryMailService
from app.services.portals.base import PolledEvent
from app.worker.jobs import ApplyMemoryMail

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _org(db: AsyncSession) -> tuple[Organization, User, User]:
    owner = User(email=f"{uuid.uuid4()}@example.org", hashed_password="x", full_name="Owner")
    reader = User(email=f"{uuid.uuid4()}@example.org", hashed_password="x", full_name="Reader")
    db.add_all([owner, reader])
    await db.flush()
    org = Organization(
        name="Atlas", slug=f"atlas-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(org)
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=org.id, user_id=reader.id, role="viewer"),
        ]
    )
    await db.flush()
    return org, owner, reader


async def test_memory_headcount_as_of_and_retro_correction(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    scope = ClaimScope(person_owner_key(owner.id))
    book = MemoryObjectRef(kind="company", name="Atlas")
    old_date = datetime(2020, 7, 1, tzinfo=UTC)
    new_date = datetime(2026, 1, 1, tzinfo=UTC)
    await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        statement="40 employees",
        subject="headcount",
        object_ref=book,
        effective_from=new_date,
    )
    old = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            statement="20 employees",
            subject="headcount",
            object_ref=book,
            effective_from=old_date,
            effective_to=old_date + timedelta(days=1),
        )
    ).claim
    assert old.object_id is not None
    before = datetime.now(UTC)
    user = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    memory = MemoryService(db)
    corrected = await memory.correct_claim(
        user, old.id, MemoryClaimCorrect(statement="22 employees", historical=True)
    )
    assert corrected.id != old.id and corrected.effective_from == old_date
    with pytest.raises(ConflictError):
        await memory.correct_claim(
            user, old.id, MemoryClaimCorrect(statement="Another number", historical=True)
        )
    with pytest.raises(BadRequestError):
        await memory.correct_claim(
            user,
            corrected.id,
            MemoryClaimCorrect(
                statement="Another number", effective_from=new_date, historical=True
            ),
        )
    timeline = await memory.object_timeline(
        user,
        library="personal",
        object_id=old.object_id,
        as_of=old_date,
        known_at=before,
        cursor=None,
        limit=10,
    )
    assert [(item.statement, item.status, item.effective_to) for item in timeline.items] == [
        ("20 employees", "current", old_date + timedelta(days=1))
    ]

    async def recalled(valid: datetime | None, known: datetime | None = None) -> list[str]:
        return [
            row.statement
            for row in await claims.recall(
                db,
                organization_id=org.id,
                scopes=[scope],
                query="Atlas employees",
                as_of=valid,
                known_at=known,
            )
        ]

    assert await recalled(old_date, before) == ["20 employees"]
    assert await recalled(old_date) == ["22 employees"]
    assert await recalled(old_date + timedelta(days=1)) == []
    assert await recalled(datetime(2023, 4, 1, tzinfo=UTC)) == []
    assert await recalled(new_date) == ["40 employees"]
    assert await recalled(None) == ["40 employees"]


async def test_memory_relevance_after_noise(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    scope = ClaimScope(person_owner_key(owner.id))
    first = await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        statement="Atlas commitment deadline Friday",
    )
    for index in range(32):
        await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            statement=f"Unrelated deadline {index}",
        )
    matches = await claims.recall(
        db,
        organization_id=org.id,
        scopes=[scope],
        query="Atlas commitment deadline",
        limit=8,
    )
    assert matches[0].id == first.claim.id


async def test_project_no_workspace_and_group_revocation(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    other, outsider, _ = await _org(db)
    editor = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    outsider_ctx = AuthContext(user_id=outsider.id, organization_id=other.id, role="owner")
    project = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=ClaimScope(person_owner_key(owner.id)),
            statement="Atlas owns project XYZ",
            object_ref=MemoryObjectRef(kind="project", name="XYZ"),
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        )
    ).claim
    group = Group(organization_id=org.id, name="Sales")
    db.add(group)
    await db.flush()
    membership = GroupMember(group_id=group.id, user_id=reader.id)
    db.add(membership)
    await db.flush()

    store = MemoryService(db)
    with pytest.raises(AuthorizationError):
        await store.publish_claim(viewer, project.id, MemoryClaimShare(confirmed=True))
    published = await store.publish_claim(
        editor, project.id, MemoryClaimShare(group_id=group.id, confirmed=True)
    )
    assert published.object_id is not None
    assert published.scope == "group"
    assert published.effective_from == project.effective_from
    options = {
        "library": "organization",
        "object_id": published.object_id,
        "as_of": None,
        "known_at": None,
        "cursor": None,
        "limit": 25,
    }
    timeline = await store.object_timeline(viewer, **options)
    assert timeline.object.name == "XYZ"
    assert [row.id for row in timeline.items] == [published.id]
    proof = await store.shared_claim_detail(viewer, published.id)
    assert proof.sources == [] and proof.withheld == 0
    with pytest.raises(NotFoundError):
        await store.object_timeline(outsider_ctx, **options)
    await db.delete(membership)
    await db.flush()
    with pytest.raises(NotFoundError):
        await store.object_timeline(viewer, **options)
    with pytest.raises(NotFoundError):
        await store.shared_claim_detail(viewer, published.id)


async def _mail(db: AsyncSession, mode: str = "active"):
    org, owner, reader = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    grant = McpConnection(
        organization_id=org.id,
        scope="org",
        purpose="portal",
        portal_key="google",
        name="Gmail",
        url="https://example.test",
        auth_type="oauth",
        oauth_payload="test-sentinel",
    )
    db.add(grant)
    await db.flush()
    service = MemoryMailService(db)
    result = await service.configure(
        ctx,
        MemoryMailConfig(
            sender="desk@example.org",
            subject="XYZ delivery deadline",
            commitment="XYZ handoff",
            mode=mode,
            notify=True,
            confirmed=True,
        ),
    )
    assert result.authorized
    return org, owner, reader, ctx, grant, service


def _delivery(
    id_: str, text: str, *, authenticated: bool = True, received: datetime | None = None
) -> PolledEvent:
    return PolledEvent(
        delivery_id=f"gmail:{id_}",
        payload={
            "from": "Desk <desk@example.org>",
            "subject": "XYZ delivery deadline",
            "text": text,
            "authenticated": authenticated,
            "received_at": (received or datetime.now(UTC)).isoformat(),
        },
    )


async def _event(db: AsyncSession, org: Organization, key: str) -> ApplyMemoryMail:
    id_ = await db.scalar(
        select(MemoryMailEvent.id).where(
            MemoryMailEvent.organization_id == org.id,
            MemoryMailEvent.delivery_id == f"gmail:{key}",
        )
    )
    assert id_ is not None
    return ApplyMemoryMail(organization_id=org.id, event_id=id_)


async def test_gmail_deadline_change_is_single_and_revocable(db: AsyncSession) -> None:
    org, owner, _, ctx, grant, service = await _mail(db)
    first = _delivery("a", "Deadline: 2026-12-01")
    second = _delivery("b", "Deadline: 2026-12-03")
    malformed = _delivery("malformed", "Deadline: 2026-02-31")
    forged = _delivery("forged", "Deadline: 2026-12-10", authenticated=False)
    assert await service.subscribed(grant, "gmail")
    assert not await service.subscribed(grant, "outlook")
    assert (await service.admit(grant, (first, first, second, malformed, forged))).queued == 2
    await service.apply(await _event(db, org, "a"))
    later = await _event(db, org, "b")
    await service.apply(later)
    await service.apply(later)
    items = await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)
    assert len(items) == 1
    assert items[0].payload["deadline_before"] == "XYZ handoff deadline: 2026-12-01"
    assert items[0].payload["deadline_after"] == "XYZ handoff deadline: 2026-12-03"

    share = ClaimScope(organization_owner_key(org.id))
    assert [
        row.statement
        for row in await claims.recall(
            db,
            organization_id=org.id,
            scopes=[share],
            query="XYZ deadline",
        )
    ] == ["XYZ handoff deadline: 2026-12-03"]

    grant.authorization_generation = uuid.uuid4()
    await db.flush()
    assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id) == []
    assert (
        await claims.recall(db, organization_id=org.id, scopes=[share], query="XYZ deadline") == []
    )
    await service.disable(ctx)
    assert await service.configuration(ctx) is None
    await service.apply(later)


async def test_gmail_shadow_and_revoked_while_queued(db: AsyncSession) -> None:
    org, _, _, ctx, grant, service = await _mail(db, "shadow")
    assert (await service.admit(grant, (_delivery("preview", "Deadline: 2026-12-01"),))).queued == 1
    await service.apply(await _event(db, org, "preview"))
    preview = await service.configuration(ctx)
    assert preview is not None and preview.last_outcome == "shadow"
    assert (await service.admit(grant, (_delivery("revoked", "Deadline: cancelled"),))).queued == 1
    queued = await _event(db, org, "revoked")
    grant.is_enabled = False
    await db.flush()
    await service.apply(queued)
    revoked = await service.configuration(ctx)
    assert revoked is not None and not revoked.authorized and revoked.last_outcome == "withheld"


async def test_same_named_people_require_separate_external_identity(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    scope = ClaimScope(person_owner_key(owner.id))
    ids = set()
    for external in ("directory:atlas:10", "directory:aura:10", "directory:atlas:10"):
        recorded = await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            statement="Anna Nowak reviews contracts",
            object_ref=MemoryObjectRef(kind="person", name="Anna Nowak", external_key=external),
        )
        ids.add(recorded.claim.object_id)
    assert len(ids) == 2

    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    page = await MemoryService(db).objects(
        ctx, library="personal", kind="person", q="Anna", cursor=None, limit=1
    )
    assert len(page.items) == 1 and page.next_cursor == page.items[0].id
    later = await MemoryService(db).objects(
        ctx, library="personal", kind="person", q="Anna", cursor=page.next_cursor, limit=1
    )
    assert later.items[0].id != page.items[0].id and later.next_cursor is None


async def test_erasure_removes_shared_copy_and_old_job_cannot_restore_it(db: AsyncSession) -> None:
    org, owner, _, ctx, grant, service = await _mail(db)
    event = _delivery("old", "Deadline: 2026-12-01")
    assert (await service.admit(grant, (event,))).queued == 1
    queued = await _event(db, org, "old")
    await service.disable(ctx)
    await service.apply(queued)
    assert (await service.admit(grant, (event,))).queued == 0

    source = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(owner.id)),
        statement="Sensitive XYZ plan",
        object_ref=MemoryObjectRef(kind="project", name="XYZ"),
    )
    store = MemoryService(db)
    copied = await store.publish_claim(ctx, source.claim.id, MemoryClaimShare(confirmed=True))
    assert copied.object_id is not None
    await store.forget_person(ctx, owner.id)
    with pytest.raises(NotFoundError):
        await store.shared_claim_detail(ctx, copied.id)
    with pytest.raises(NotFoundError):
        await store.object_timeline(
            ctx,
            library="organization",
            object_id=copied.object_id,
            as_of=None,
            known_at=None,
            cursor=None,
            limit=10,
        )


async def test_late_email_fills_its_interval_without_another_alert(db: AsyncSession) -> None:
    org, owner, _, _, grant, service = await _mail(db)
    received = datetime.now(UTC)
    first = _delivery("a", "Deadline: 2026-12-01", received=received)
    late = _delivery("b", "Deadline: 2026-12-02", received=received + timedelta(seconds=1))
    latest = _delivery("c", "Deadline: 2026-12-03", received=received + timedelta(seconds=2))
    assert (await service.admit(grant, (first, latest, late))).queued == 3
    for key in ("a", "c", "b"):
        await service.apply(await _event(db, org, key))
    share = ClaimScope(organization_owner_key(org.id))
    for offset, end in ((0, "01"), (1, "02"), (2, "03")):
        matches = await claims.recall(
            db,
            organization_id=org.id,
            scopes=[share],
            query="XYZ deadline",
            as_of=received + timedelta(seconds=offset),
        )
        assert [item.value for item in matches] == [f"2026-12-{end}"]
    assert len(await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)) == 1


async def test_shared_note_is_a_reviewed_snapshot_and_erasure_cascades(db: AsyncSession) -> None:
    org, owner, viewer = await _org(db)
    editor = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    member = AuthContext(user_id=viewer.id, organization_id=org.id, role="viewer")
    agent = Agent(
        organization_id=org.id, slug="handoff", name="Handoff", created_by_user_id=owner.id
    )
    db.add(agent)
    await db.flush()
    note = AgentMemoryFile(
        organization_id=org.id,
        agent_id=agent.id,
        owner_key=person_owner_key(owner.id),
        name="handoff.md",
        content="Reviewed content",
    )
    db.add(note)
    await db.flush()
    memory = MemoryService(db)
    with pytest.raises(ConflictError):
        await memory.publish_note(
            editor,
            note.id,
            MemoryNoteShare(confirmed=True, expected_updated_at=datetime.now(UTC)),
        )
    shared = await memory.publish_note(
        editor, note.id, MemoryNoteShare(confirmed=True, expected_updated_at=note.updated_at)
    )
    note.content = "Private changes after publication"
    await db.flush()
    result = await memory.shared_notes(member, cursor=None, limit=10)
    assert [(item.id, item.content) for item in result.items] == [(shared.id, "Reviewed content")]
    await memory.forget_person(editor, owner.id)
    assert (await memory.shared_notes(member, cursor=None, limit=10)).items == []


async def test_gmail_backpressure_preserves_unadmitted_events(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.memory import mail

    org, _, _, ctx, grant, service = await _mail(db)
    monkeypatch.setattr(mail, "MAX_DAILY_EVENTS", 1)
    assert (await service.admit(grant, ())).complete
    first = _delivery("a", "Deadline: 2026-12-01")
    second = _delivery("b", "Deadline: 2026-12-02")
    offered = await service.admit(grant, (first, first, second))
    assert offered.queued == 1 and not offered.complete
    capped = await service.configuration(ctx)
    assert capped is not None and capped.last_outcome == "daily_limit"
    assert (await service.admit(grant, (first,))).complete
    assert not (await service.admit(grant, (second,))).complete
    monkeypatch.setattr(mail, "MAX_DAILY_EVENTS", 2)
    assert (await service.admit(grant, (first, second))).queued == 1

    await service.apply(await _event(db, org, "a"))
    await service.apply(await _event(db, org, "b"))
    shared = await MemoryService(db).shared_claims(ctx, q="XYZ", skip=0, limit=10)
    assert [item.value for item in shared.items] == ["2026-12-02"]
    detail = await MemoryService(db).shared_claim_detail(ctx, shared.items[0].id)
    assert [item.quote for item in detail.evidence] == ["Deadline: 2026-12-02"]
