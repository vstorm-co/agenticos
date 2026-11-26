"""Company/personal memory replay on the real ledger and queue."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import AwareDatetime, BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.memory_keys import organization_owner_key, person_owner_key, room_owner_key
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.group import Group, GroupMember
from app.db.models.mcp_connection import McpConnection
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import MemoryClaim, MemoryMailEvent
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import memory_claim, suggestion_repo
from app.repositories.memory_claim import ClaimScope
from app.schemas.decision_episode import DecisionEpisode
from app.schemas.memory import (
    MemoryClaimCorrect,
    MemoryClaimShare,
    MemoryConflictResolve,
    MemoryMailConfig,
    MemoryNoteShare,
    MemoryObjectRef,
)
from app.services.memory import MemoryService, claims, runtime
from app.services.memory.mail import MemoryMailService
from app.services.memory.sources import SourceObservation, apply_observation
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


async def _mail(db: AsyncSession, mode: str = "active", *, object_key: str | None = None):
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
    result = await MemoryService(db).configure_memory_mail(
        ctx,
        MemoryMailConfig(
            sender="desk@example.org",
            subject="XYZ delivery deadline",
            commitment="XYZ handoff",
            object_key=object_key,
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
    await MemoryService(db).disable_memory_mail(ctx)
    assert await MemoryService(db).memory_mail(ctx) is None
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


async def test_reviewers_losing_edit_scope_stop_polling_admission_and_apply(
    db: AsyncSession,
) -> None:
    org, owner, _, _, grant, service = await _mail(db)
    event = _delivery("a", "Deadline: 2026-12-01")
    assert (await service.admit(grant, (event,))).queued == 1

    membership = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id, OrganizationMember.user_id == owner.id
        )
    )
    assert membership is not None
    membership.role = "viewer"
    await db.flush()

    assert not await service.subscribed(grant, "gmail")
    assert (await service.admit(grant, (_delivery("b", "Deadline: 2026-12-02"),))).queued == 0
    queued = await _event(db, org, "a")
    await service.apply(queued)
    stored = await db.get(MemoryMailEvent, queued.event_id)
    assert stored is not None and stored.state == "withheld"


async def test_object_versions_use_stable_cursors_and_amend_legacy_rows(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    store = MemoryService(db)
    key = person_owner_key(owner.id)
    entity = await memory_claim.put_object(
        db,
        organization_id=org.id,
        scope_key=key,
        kind="company",
        name="Atlas",
        identity_key="name:atlas",
    )
    old_date = datetime(2020, 1, 1, tzinfo=UTC)
    old = MemoryClaim(
        organization_id=org.id,
        scope_key=key,
        object_id=entity.id,
        subject="headcount",
        statement="20 employees",
        effective_from=old_date,
        effective_to=old_date + timedelta(days=1),
        observed_at=old_date + timedelta(days=1),
    )
    db.add(old)
    await db.flush()
    await memory_claim.set_status(db, old, "current")
    with pytest.raises(BadRequestError):
        await store.correct_claim(
            ctx,
            old.id,
            MemoryClaimCorrect(
                statement="Not a decision",
                historical=True,
                episode=DecisionEpisode(situation="Test", choice="Choose a value"),
            ),
        )
    latest = await store.correct_claim(
        ctx, old.id, MemoryClaimCorrect(statement="22 employees", historical=True)
    )
    page = await store.object_timeline(
        ctx,
        library="personal",
        object_id=entity.id,
        as_of=None,
        known_at=None,
        cursor=None,
        limit=1,
    )
    assert [case.id for case in page.items] == [latest.id] and page.next_cursor == latest.id
    next_page = await store.object_timeline(
        ctx,
        library="personal",
        object_id=entity.id,
        as_of=None,
        known_at=None,
        cursor=page.next_cursor,
        limit=1,
    )
    assert [case.id for case in next_page.items] == [old.id] and next_page.next_cursor is None
    ago = await store.object_timeline(
        ctx,
        library="personal",
        object_id=entity.id,
        as_of=old_date,
        known_at=old_date + timedelta(days=2),
        cursor=None,
        limit=5,
    )
    assert ago.items[0].statement == "20 employees"
    none_found = await store.object_timeline(
        ctx,
        library="personal",
        object_id=entity.id,
        as_of=old_date,
        known_at=old_date,
        cursor=None,
        limit=5,
    )
    assert none_found.items == []
    with pytest.raises(BadRequestError):
        await store.object_timeline(
            ctx,
            library="personal",
            object_id=entity.id,
            as_of=None,
            known_at=old_date,
            cursor=None,
            limit=5,
        )
    with pytest.raises(BadRequestError):
        await claims.remember(
            db,
            organization_id=org.id,
            scope=ClaimScope(key),
            statement="Invalid range",
            effective_from=old_date,
            effective_to=old_date,
        )


async def test_group_claim_recall_keeps_private_audience_boundaries(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, owner, reader = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    group = Group(organization_id=org.id, name="Sales")
    db.add(group)
    await db.flush()
    membership = GroupMember(group_id=group.id, user_id=reader.id)
    db.add(membership)
    await db.flush()
    personal_claim = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(owner.id)),
        statement="Atlas handoff visibility",
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
    )
    await MemoryService(db).publish_claim(
        ctx,
        personal_claim.claim.id,
        MemoryClaimShare(group_id=group.id, confirmed=True),
    )
    with pytest.raises(NotFoundError):
        await MemoryService(db).publish_claim(
            ctx,
            personal_claim.claim.id,
            MemoryClaimShare(group_id=uuid.uuid4(), confirmed=True),
        )

    @asynccontextmanager
    async def current_db():
        yield db

    monkeypatch.setattr(runtime, "get_db_context", current_db)
    matching = await runtime.recall(
        organization_id=org.id,
        scopes=[ClaimScope(person_owner_key(reader.id))],
        query="Atlas handoff",
        as_of=datetime(2022, 1, 1, tzinfo=UTC),
        known_at=datetime.now(UTC),
        reading_member=reader.id,
        include_groups=True,
    )
    assert [row.scope for row in matching] == ["group"]
    assert not await runtime.recall(
        organization_id=org.id,
        scopes=[ClaimScope(room_owner_key("slack", "room"))],
        query="Atlas handoff",
    )
    assert not await runtime.recall(
        organization_id=org.id,
        scopes=[ClaimScope(organization_owner_key(org.id))],
        query="Atlas handoff",
        reading_member=uuid.uuid4(),
        include_groups=True,
    )

    store = MemoryService(db)
    with pytest.raises(AuthorizationError):
        await store.objects(
            AuthContext(
                user_id=reader.id,
                organization_id=org.id,
                role="viewer",
                key_scopes=frozenset({Perm.CONTEXT_VIEW}),
            ),
            library="organization",
            kind=None,
            q="",
            cursor=None,
            limit=5,
        )
    await store.publish_claim(ctx, personal_claim.claim.id, MemoryClaimShare(confirmed=True))
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org.id, OrganizationMember.user_id == reader.id
        )
    )
    assert member is not None
    member.role = "retired-role"
    await db.flush()
    with pytest.raises(AuthorizationError):
        await store.shared_claims(
            AuthContext(user_id=reader.id, organization_id=org.id, role=member.role),
            q="Atlas",
            limit=5,
            skip=0,
        )
    assert not await runtime.recall(
        organization_id=org.id,
        scopes=[ClaimScope(organization_owner_key(org.id))],
        query="Atlas handoff",
        reading_member=reader.id,
        include_groups=True,
    )


async def test_mail_rule_reconnect_removes_old_history_and_proofs(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker.tasks import memory_tasks

    org, owner, reader, ctx, grant, service = await _mail(db)
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    data = MemoryMailConfig(
        sender="desk@example.org",
        subject="XYZ delivery deadline",
        commitment="XYZ handoff",
        mode="active",
        notify=True,
        confirmed=True,
    )
    with pytest.raises(AuthorizationError):
        await service.configure(viewer, data)
    with pytest.raises(BadRequestError):
        await service.configure(
            AuthContext(user_id=owner.id, organization_id=uuid.uuid4(), role="owner"), data
        )

    no_date = _delivery("no-date", "Deadline ASAP")
    before = _delivery(
        "before",
        "Deadline: 2026-10-01",
        received=datetime.now(UTC) - timedelta(days=1),
    )
    assert (await service.admit(grant, (no_date, before))).queued == 0
    candidates = (
        _delivery("a", "Deadline: 2026-12-01"),
        _delivery("b", "Deadline: 2026-12-01"),
        _delivery("c", "Deadline: cancelled"),
    )
    assert (await service.admit(grant, candidates)).queued == 3

    @asynccontextmanager
    async def current_db():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", current_db)
    for key in ("a", "b", "c"):
        await memory_tasks.apply_memory_mail(await _event(db, org, key))
    found = await MemoryService(db).shared_claims(ctx, q="XYZ", limit=5, skip=0)
    assert [item.statement for item in found.items] == ["XYZ handoff deadline cancelled"]
    assert len(await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)) == 1

    grant.authorization_generation = uuid.uuid4()
    await db.flush()
    replacement = await service.configure(ctx, data)
    assert replacement.authorized and replacement.last_outcome is None
    assert (
        await db.scalar(select(MemoryMailEvent.id).where(MemoryMailEvent.organization_id == org.id))
        is None
    )
    assert (await MemoryService(db).shared_claims(ctx, q="XYZ", limit=5, skip=0)).total == 0
    assert not await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)


async def test_mail_rule_reconfiguration_fences_queued_items_and_ties(db: AsyncSession) -> None:
    org, owner, _, ctx, grant, service = await _mail(db)
    stamp = datetime.now(UTC)
    events = (
        _delivery("a", "Deadline: 2026-12-01", received=stamp),
        _delivery("tie", "Deadline: 2026-12-02", received=stamp),
        _delivery("pending", "Deadline: 2026-12-03"),
    )
    assert (await service.admit(grant, events)).queued == 3
    for key in ("a", "tie"):
        await service.apply(await _event(db, org, key))
    data = MemoryMailConfig(
        sender="desk@example.org",
        subject="XYZ delivery deadline",
        commitment="XYZ handoff",
        mode="shadow",
        notify=False,
        confirmed=True,
    )
    await service.configure(ctx, data)
    await service.apply(await _event(db, org, "pending"))
    config = await service.configuration(ctx)
    assert config is not None and config.last_outcome == "withheld"
    assert not await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id)
    conflicts = await MemoryService(db).shared_claims(ctx, q="XYZ", limit=10, skip=0, disputed=True)
    assert {row.value for row in conflicts.items} == {"2026-12-01", "2026-12-02"}
    await service.disable(ctx)
    await service.disable(ctx)


async def test_queued_mail_disappearing_during_recheck_has_no_side_effects(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, _, _, ctx, grant, service = await _mail(db)
    await service.admit(grant, (_delivery("a", "Deadline: 2026-12-01"),))
    payload = await _event(db, org, "a")
    real = memory_claim.mail_source

    async def remove_before_lock(session, organization_id, *, lock=False):
        if lock:
            source = await real(session, organization_id, lock=True)
            assert source is not None
            await memory_claim.remove_mail_source(session, source)
        return await real(session, organization_id, lock=lock)

    monkeypatch.setattr(memory_claim, "mail_source", remove_before_lock)
    await service.apply(payload)
    assert await service.configuration(ctx) is None
    assert (await MemoryService(db).shared_claims(ctx, q="XYZ", limit=10, skip=0)).total == 0


async def test_share_cannot_copy_an_object_from_a_different_scope(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    object_row = await memory_claim.put_object(
        db,
        organization_id=org.id,
        scope_key=person_owner_key(reader.id),
        kind="project",
        name="Other member's project",
        identity_key="name:private",
    )
    # A damaged import with an incorrect foreign key must not disclose the other
    # store's object or silently turn the shared claim into an unbound record.
    claim = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=person_owner_key(owner.id),
        object_id=object_row.id,
        statement="A dated observation",
        observed_at=datetime.now(UTC),
    )
    store = MemoryService(db)
    actor = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    with pytest.raises(ConflictError):
        await store.publish_claim(actor, claim.id, MemoryClaimShare(confirmed=True))
    assert (await store.shared_claims(actor, q="", limit=10, skip=0)).total == 0


_HANDOFF_KEY = "business:atlas-handoff"


async def _chat_deadline(
    db: AsyncSession,
    org: Organization,
    owner: User,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> uuid.UUID:
    @asynccontextmanager
    async def current_db():
        yield db

    monkeypatch.setattr(runtime, "get_db_context", current_db)
    result = await runtime.remember(
        organization_id=org.id,
        scope=ClaimScope(person_owner_key(owner.id)),
        statement=f"The chat confirmed {value} for XYZ handoff in the customer call.",
        subject="deadline",
        kind="fact",
        author_user_id=owner.id,
        conversation_id=None,
        run_id=None,
        effective_from=None,
        object_ref=MemoryObjectRef(
            kind="commitment", name="XYZ handoff", external_key=_HANDOFF_KEY
        ),
        value=value,
    )
    assert result is not None
    return result[0].id


@pytest.mark.parametrize("chat_first", [True, False])
async def test_chat_gmail_agreement_keeps_both_sources(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, chat_first: bool
) -> None:
    org, owner, reader, ctx, grant, mail = await _mail(db, object_key=_HANDOFF_KEY)
    store = MemoryService(db)
    private = await _chat_deadline(db, org, owner, "2026-12-01", monkeypatch)
    share = MemoryClaimShare(confirmed=True)
    if chat_first:
        published = await store.publish_claim(ctx, private, share)
    events = (
        _delivery("first", "Deadline: 2026-12-01"),
        _delivery("second", "Deadline: 2026-12-01"),
    )
    assert (await mail.admit(grant, events)).queued == 2
    for key in ("first", "second"):
        await mail.apply(await _event(db, org, key))
    before_publication = (await store.shared_claims(ctx, q="", skip=0, limit=10)).items
    assert len(before_publication) == 1
    if not chat_first:
        assert before_publication[0].derived_from_count == 0
        published = await store.publish_claim(ctx, private, share)
    assert published.id == before_publication[0].id

    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    detail = await store.shared_claim_detail(viewer, published.id)
    assert detail.derived_from_count == 0  # The organization API does not expose private ancestry.
    assert detail.sources == []
    assert {item.source_id for item in detail.evidence} == {"gmail:first", "gmail:second"}
    assert len((await store.shared_claims(viewer, q="", skip=0, limit=10)).items) == 1
    if chat_first:
        await store.forget_person(ctx, owner.id)
        detail = await store.shared_claim_detail(viewer, published.id)
        assert detail.statement == "XYZ handoff deadline: 2026-12-01"
        assert len(detail.evidence) == 2
        await mail.disable(ctx)
        with pytest.raises(NotFoundError):
            await store.shared_claim_detail(viewer, published.id)
    else:
        grant.authorization_generation = uuid.uuid4()
        await db.flush()
        detail = await store.shared_claim_detail(viewer, published.id)
        assert detail.evidence == []
        assert detail.statement == "XYZ handoff deadline: 2026-12-01"
        await mail.disable(ctx)
        assert (await store.shared_claim_detail(viewer, published.id)).evidence == []
        await store.forget_person(ctx, owner.id)
        with pytest.raises(NotFoundError):
            await store.shared_claim_detail(viewer, published.id)


@pytest.mark.parametrize(("chat_first", "keep_chat"), [(True, True), (False, True), (True, False)])
async def test_conflicting_chat_and_gmail_need_a_member_decision(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, chat_first: bool, keep_chat: bool
) -> None:
    org, owner, reader, ctx, grant, mail = await _mail(db, object_key=_HANDOFF_KEY)
    store = MemoryService(db)
    private = await _chat_deadline(db, org, owner, "2026-12-02", monkeypatch)
    if chat_first:
        published = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    event = _delivery("email", "Deadline: 2026-12-01")
    assert (await mail.admit(grant, (event,))).queued == 1
    await mail.apply(await _event(db, org, "email"))
    if not chat_first:
        published = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    contested = (
        await store.shared_claims(ctx, q="deadline", skip=0, limit=10, disputed=True)
    ).items
    assert contested
    stored = await store.shared_claim_detail(ctx, published.id)
    assert {row.value for row in stored.conflicts} == {"2026-12-01", "2026-12-02"}
    assert await suggestion_repo.list_open(db, organization_id=org.id, user_id=owner.id) == []
    data = MemoryConflictResolve(candidate_ids=[row.id for row in stored.conflicts])
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    with pytest.raises(AuthorizationError):
        await store.resolve_shared_conflict(viewer, published.id, data)
    with pytest.raises(ConflictError):
        await store.resolve_shared_conflict(
            ctx, published.id, MemoryConflictResolve(candidate_ids=[published.id, uuid.uuid4()])
        )
    elsewhere, other_owner, _ = await _org(db)
    with pytest.raises(NotFoundError):
        await store.resolve_shared_conflict(
            AuthContext(user_id=other_owner.id, organization_id=elsewhere.id, role="owner"),
            published.id,
            data,
        )
    kept = (
        published if keep_chat else next(row for row in stored.conflicts if row.id != published.id)
    )
    winner = await store.resolve_shared_conflict(ctx, kept.id, data)
    assert winner.status == "current"
    assert (await store.shared_claim_detail(ctx, published.id)).conflicts == []
    if not keep_chat:
        older = await store.shared_claim_detail(ctx, published.id)
        assert older.status == "superseded" and older.effective_to is not None
    assert (await store.shared_claims(ctx, q="", skip=0, limit=10, disputed=True)).total == 0
    with pytest.raises(ConflictError):
        await store.resolve_shared_conflict(ctx, published.id, data)
    assert [
        row.value
        for row in await claims.recall(
            db,
            organization_id=org.id,
            scopes=[ClaimScope(organization_owner_key(org.id))],
            query="XYZ deadline",
        )
    ] == [kept.value]


class CrmDealFixture(BaseModel):
    account: str
    deal_id: str
    handoff_key: str
    handoff_label: str
    target_date: date
    changed_at: AwareDatetime

    def observation(self) -> SourceObservation:
        value = self.target_date.isoformat()
        return SourceObservation(
            source_key=f"crm:{self.account}/{self.deal_id}",
            delivery_id=f"crm:{self.account}/{self.deal_id}/{self.changed_at.isoformat()}",
            quote=f"target_date={value}",
            object=MemoryObjectRef(
                kind="commitment", name=self.handoff_label, external_key=self.handoff_key
            ),
            subject="deadline",
            statement=f"CRM target date for {self.handoff_label}: {value}",
            value=value,
            effective_at=self.changed_at,
        )


async def test_crm_fixture_through_shared_memory_contract(db: AsyncSession) -> None:
    fixture = Path(__file__).resolve().parents[3] / "evals/personal/fixtures/memory_crm.json"
    rows = TypeAdapter(list[CrmDealFixture]).validate_json(fixture.read_bytes())
    org, owner, _ = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    store = MemoryService(db)

    async def apply(index: int):
        return await apply_observation(
            db, organization_id=org.id, observation=rows[index].observation()
        )

    first = await apply(0)
    assert first.memory.created
    replay = await apply(0)
    assert not replay.memory.created
    assert replay.memory.claim.id == first.memory.claim.id
    corrected = await apply(1)
    assert corrected.previous is not None and corrected.previous.id == first.memory.claim.id
    replay = await apply(0)
    assert not replay.memory.created and replay.memory.claim.id == first.memory.claim.id
    assert corrected.memory.claim.object_id == first.memory.claim.object_id
    reverted = await apply(2)
    assert reverted.previous is not None and reverted.previous.id == corrected.memory.claim.id
    assert reverted.memory.claim.id != first.memory.claim.id
    contested = await apply(3)
    assert contested.memory.disputed
    detail = await store.shared_claim_detail(ctx, contested.memory.claim.id)
    assert {row.value for row in detail.conflicts} == {"2026-12-01", "2026-12-03"}


async def test_source_contract_refuses_a_mismatched_admitted_proof(db: AsyncSession) -> None:
    org, _, _, _, grant, mail = await _mail(db)
    delivery = _delivery("original", "Deadline: 2026-12-01")
    assert (await mail.admit(grant, (delivery,))).queued == 1
    job = await _event(db, org, "original")
    event = await memory_claim.mail_event(db, organization_id=org.id, event_id=job.event_id)
    assert event is not None
    observation = SourceObservation(
        source_key="gmail:rule",
        delivery_id=event.delivery_id,
        quote="wrong proof",
        object=MemoryObjectRef(kind="commitment", name="XYZ"),
        subject="deadline",
        statement="Deadline is 2026-12-01",
        value="2026-12-01",
        effective_at=event.received_at,
    )
    with pytest.raises(BadRequestError, match="admitted Gmail evidence"):
        await apply_observation(
            db, organization_id=org.id, observation=observation, mail_event=event
        )
    with pytest.raises(BadRequestError, match="normalized subject"):
        await apply_observation(
            db, organization_id=org.id, observation=observation.model_copy(update={"subject": "."})
        )


async def test_mail_rule_without_its_reviewer_withholds_queued_evidence(db: AsyncSession) -> None:
    org, _, _, ctx, grant, mail = await _mail(db)
    delivery = _delivery("original", "Deadline: 2026-12-01")
    assert (await mail.admit(grant, (delivery,))).queued == 1
    source = await memory_claim.mail_source(db, org.id)
    assert source is not None
    source.reviewer_id = None
    await db.flush()
    assert not await mail.subscribed(grant, "gmail")
    await mail.apply(await _event(db, org, "original"))
    config = await mail.configuration(ctx)
    assert config is not None and config.last_outcome == "withheld"
    assert (await MemoryService(db).shared_claims(ctx, q="", skip=0, limit=5)).total == 0


async def test_retaining_mail_after_erasing_a_closed_chat_publication(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, owner, _, ctx, grant, mail = await _mail(db, object_key=_HANDOFF_KEY)
    store = MemoryService(db)
    first = await _chat_deadline(db, org, owner, "2026-12-01", monkeypatch)
    published = await store.publish_claim(ctx, first, MemoryClaimShare(confirmed=True))
    received = datetime.now(UTC)
    assert (
        await mail.admit(grant, (_delivery("agree", "Deadline: 2026-12-01", received=received),))
    ).queued == 1
    await mail.apply(await _event(db, org, "agree"))
    revised = await _chat_deadline(db, org, owner, "2026-12-02", monkeypatch)
    other = await store.publish_claim(ctx, revised, MemoryClaimShare(confirmed=True))
    assert other.status == "disputed"
    decision = MemoryConflictResolve(candidate_ids=[published.id, other.id])
    await store.resolve_shared_conflict(ctx, other.id, decision)

    await store.forget_person(ctx, owner.id)
    retained = await store.shared_claim_detail(ctx, published.id)
    assert retained.statement == "XYZ handoff deadline: 2026-12-01"
    assert retained.effective_from == received and retained.effective_to is not None
    assert retained.status == "superseded"
    assert (await store.shared_claims(ctx, q="", skip=0, limit=10)).total == 0


async def test_an_observation_before_a_scheduled_revision_cannot_overwrite_reviewed_memory(
    db: AsyncSession,
) -> None:
    org, _, _, _, grant, mail = await _mail(db, object_key=_HANDOFF_KEY)
    scope = ClaimScope(organization_owner_key(org.id))
    ref = MemoryObjectRef(kind="commitment", name="XYZ handoff", external_key=_HANDOFF_KEY)
    now = datetime.now(UTC)
    first = await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        object_ref=ref,
        origin="person",
        subject="deadline",
        statement="XYZ deadline is Dec 1",
        value="2026-12-01",
        effective_from=now - timedelta(days=1),
    )
    await claims.remember(
        db,
        organization_id=org.id,
        scope=scope,
        object_ref=ref,
        origin="person",
        subject="deadline",
        statement="XYZ deadline is Dec 2 from tomorrow",
        value="2026-12-02",
        effective_from=now + timedelta(days=1),
    )
    assert (await mail.admit(grant, (_delivery("contradict", "Deadline: 2026-12-03"),))).queued == 1
    await mail.apply(await _event(db, org, "contradict"))
    recalled = await claims.recall(db, organization_id=org.id, scopes=[scope], query="XYZ deadline")
    assert [item.id for item in recalled if item.status == "current"] == [first.claim.id]
    assert [item.value for item in recalled if item.status == "disputed"] == ["2026-12-03"]
    assert first.claim.effective_to == now + timedelta(days=1)
