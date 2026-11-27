"""Company/personal memory replay on the real ledger and queue."""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import AwareDatetime, BaseModel, TypeAdapter
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.memory_keys import organization_owner_key, person_owner_key, room_owner_key
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.background_job import BackgroundJob
from app.db.models.group import Group, GroupMember
from app.db.models.mcp_connection import McpConnection
from app.db.models.memory import AgentMemoryFile
from app.db.models.memory_claim import MemoryClaim, MemoryMailEvent
from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.db.models.workflow_exposure import WorkflowWebhookDelivery
from app.db.models.workflow_run import WorkflowRun, WorkflowRunMode
from app.repositories import memory_claim
from app.repositories.memory_claim import ClaimScope
from app.schemas.decision_episode import DecisionEpisode
from app.schemas.memory import (
    MemoryClaimCorrect,
    MemoryClaimShare,
    MemoryConflictResolve,
    MemoryInboxRuleUpdate,
    MemoryNoteShare,
    MemoryObjectBackfillAdvance,
    MemoryObjectBackfillRun,
    MemoryObjectKind,
    MemoryObjectMergeCreate,
    MemoryObjectRef,
)
from app.schemas.notification import NotificationRead
from app.services.memory import MemoryService, claims, runtime
from app.services.memory.sources import SourceObservation, apply_observation
from app.services.memory.workflow import MemoryObservationConfig, record_observation
from app.services.memory_inbox import deliver_memory_inbox
from app.services.notification_center import NotificationCenterService
from app.services.portals.base import PolledEvent
from app.services.workflow_exposure import WorkflowExposureService
from app.worker.jobs import (
    BACKFILL_MEMORY_OBJECTS,
    DELIVER_MEMORY_INBOX,
    BackfillMemoryObjects,
    DeliverMemoryInbox,
)
from app.worker.tasks import memory_tasks
from app.workflows.graph.model import Edge, WorkflowGraph
from tests.integration.test_workflow_exposures import _publish, _signed, _step, _webhook, _workflow

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


_HANDOFF_KEY = "business:atlas-handoff"
_CONFIG = MemoryObservationConfig(
    object_kind="commitment", object_name="XYZ handoff", object_key=_HANDOFF_KEY, subject="deadline"
)


def _observation_graph(entry: str, settings: dict[str, object] | None = None) -> WorkflowGraph:
    trigger = _step(entry, settings)
    observe = _step("memory.observe", _CONFIG.model_dump())
    return WorkflowGraph(
        entry_node_id=trigger.id,
        nodes=(trigger, observe),
        edges=(
            Edge(
                id=uuid.uuid4(),
                source_node_id=trigger.id,
                source_port="out",
                target_node_id=observe.id,
                target_port="in",
            ),
        ),
    )


async def _mail(
    db: AsyncSession, *, sender: str | None = "desk@example.org"
) -> tuple[Organization, User, User, AuthContext, McpConnection]:
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
    workflow = await _workflow(db, org=org, owner=owner)
    await _publish(
        db,
        ctx,
        workflow,
        _observation_graph(
            "trigger.gmail",
            {"sender_contains": sender, "subject_contains": "XYZ delivery deadline"},
        ),
    )
    return org, owner, reader, ctx, grant


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


async def _admit(db: AsyncSession, grant: McpConnection, *events: PolledEvent) -> None:
    assert grant.organization_id is not None
    assert await WorkflowExposureService(db).receive_polled_email(
        organization_id=grant.organization_id,
        source="gmail",
        events=events,
        connection=grant,
    )


async def _receipt(db: AsyncSession, org: Organization, key: str) -> WorkflowWebhookDelivery | None:
    return await db.scalar(
        select(WorkflowWebhookDelivery).where(
            WorkflowWebhookDelivery.organization_id == org.id,
            WorkflowWebhookDelivery.delivery_id == f"gmail:{key}",
        )
    )


async def _mail_run(db: AsyncSession, org: Organization, key: str) -> uuid.UUID:
    receipt = await _receipt(db, org, key)
    assert receipt is not None
    return receipt.workflow_run_id


async def _apply(db: AsyncSession, org: Organization, ctx: AuthContext, key: str):
    return await record_observation(
        db, auth=ctx, run_id=await _mail_run(db, org, key), config=_CONFIG
    )


async def test_gmail_deadline_change_is_single_and_revocable(db: AsyncSession) -> None:
    org, _, _, ctx, grant = await _mail(db)
    first = _delivery("a", "Deadline: 2026-12-01")
    second = _delivery("b", "Deadline: 2026-12-03")
    malformed = _delivery("malformed", "Deadline: 2026-02-31")
    forged = _delivery("forged", "Deadline: 2026-12-10", authenticated=False)
    await _admit(db, grant, first, first, second, malformed, forged)
    assert await _receipt(db, org, "forged") is None
    assert (await _apply(db, org, ctx, "a")).status == "applied"
    change = await _apply(db, org, ctx, "b")
    assert change.status == "changed" and change.changed
    assert await _apply(db, org, ctx, "b") == change
    with pytest.raises(BadRequestError, match="invalid memory observation"):
        await _apply(db, org, ctx, "malformed")

    store = MemoryService(db)
    items = (await store.shared_claims(ctx, q="", limit=10, skip=0)).items
    assert [row.statement for row in items] == ["XYZ handoff deadline: 2026-12-03"]
    detail = await store.shared_claim_detail(ctx, items[0].id)
    assert [item.quote for item in detail.evidence] == ["Deadline: 2026-12-03"]
    grant.authorization_generation = uuid.uuid4()
    await db.flush()
    assert (await store.shared_claims(ctx, q="", limit=10, skip=0)).total == 0
    with pytest.raises(AuthorizationError, match="no longer authorized"):
        await _apply(db, org, ctx, "b")


async def test_gmail_draft_and_revoked_dispatch_do_not_write(db: AsyncSession) -> None:
    org, _, reader, ctx, grant = await _mail(db)
    await _admit(db, grant, _delivery("before", "Deadline: cancelled"))
    run_id = await _mail_run(db, org, "before")
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    with pytest.raises(AuthorizationError, match="context:edit"):
        await record_observation(db, auth=viewer, run_id=run_id, config=_CONFIG)
    run = await db.get(WorkflowRun, run_id)
    assert run is not None
    # Drafts are admitted without a published run version.
    version = run.workflow_version_id
    run.mode = WorkflowRunMode.TEST
    run.workflow_version_id = None
    run.draft_graph_snapshot = _observation_graph("trigger.gmail").model_dump(mode="json")
    await db.flush()
    assert (
        await record_observation(db, auth=ctx, run_id=run_id, config=_CONFIG)
    ).status == "preview"
    run.mode = WorkflowRunMode.REAL
    run.workflow_version_id = version
    run.draft_graph_snapshot = None
    grant.is_enabled = False
    await db.flush()
    with pytest.raises(AuthorizationError, match="no longer authorized"):
        await _apply(db, org, ctx, "before")
    assert await db.scalar(select(MemoryMailEvent.id)) is None


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


async def test_erasure_removes_shared_copy(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")

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
    org, _, _, ctx, grant = await _mail(db)
    received = datetime.now(UTC) - timedelta(seconds=5)
    first = _delivery("a", "Deadline: 2026-12-01", received=received)
    late = _delivery("b", "Deadline: 2026-12-02", received=received + timedelta(seconds=1))
    latest = _delivery("c", "Deadline: 2026-12-03", received=received + timedelta(seconds=2))
    await _admit(db, grant, first, latest, late)
    assert (await _apply(db, org, ctx, "a")).status == "applied"
    assert (await _apply(db, org, ctx, "c")).changed
    outcome = await _apply(db, org, ctx, "b")
    assert outcome.status == "late" and not outcome.changed
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
    org, owner, reader, ctx, grant = await _mail(db)
    store = MemoryService(db)
    private = await _chat_deadline(db, org, owner, "2026-12-01", monkeypatch)
    share = MemoryClaimShare(confirmed=True)
    if chat_first:
        published = await store.publish_claim(ctx, private, share)
    events = (
        _delivery("first", "Deadline: 2026-12-01"),
        _delivery("second", "Deadline: 2026-12-01"),
    )
    await _admit(db, grant, *events)
    for key in ("first", "second"):
        await _apply(db, org, ctx, key)
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
    assert len({item.source_id for item in detail.evidence}) == 2
    assert {item.quote for item in detail.evidence} == {"Deadline: 2026-12-01"}
    assert len((await store.shared_claims(viewer, q="", skip=0, limit=10)).items) == 1
    if chat_first:
        await store.forget_person(ctx, owner.id)
        detail = await store.shared_claim_detail(viewer, published.id)
        assert detail.statement == "XYZ handoff deadline: 2026-12-01"
        assert len(detail.evidence) == 2
        grant.is_enabled = False
        await db.flush()
        with pytest.raises(NotFoundError):
            await store.shared_claim_detail(viewer, published.id)
    else:
        grant.authorization_generation = uuid.uuid4()
        await db.flush()
        detail = await store.shared_claim_detail(viewer, published.id)
        assert detail.evidence == []
        assert detail.statement == "XYZ handoff deadline: 2026-12-01"
        assert (await store.shared_claim_detail(viewer, published.id)).evidence == []
        await store.forget_person(ctx, owner.id)
        with pytest.raises(NotFoundError):
            await store.shared_claim_detail(viewer, published.id)


@pytest.mark.parametrize(("chat_first", "keep_chat"), [(True, True), (False, True), (True, False)])
async def test_conflicting_chat_and_gmail_need_a_member_decision(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, chat_first: bool, keep_chat: bool
) -> None:
    org, owner, reader, ctx, grant = await _mail(db)
    store = MemoryService(db)
    private = await _chat_deadline(db, org, owner, "2026-12-02", monkeypatch)
    if chat_first:
        published = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    event = _delivery("email", "Deadline: 2026-12-01")
    await _admit(db, grant, event)
    assert not (await _apply(db, org, ctx, "email")).changed
    if not chat_first:
        published = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    contested = (
        await store.shared_claims(ctx, q="deadline", skip=0, limit=10, disputed=True)
    ).items
    assert contested
    stored = await store.shared_claim_detail(ctx, published.id)
    assert {row.value for row in stored.conflicts} == {"2026-12-01", "2026-12-02"}
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
    org, _, _, ctx, grant = await _mail(db)
    await _admit(db, grant, _delivery("original", "Deadline: 2026-12-01"))
    stored = await _apply(db, org, ctx, "original")
    event = await db.scalar(
        select(MemoryMailEvent).where(MemoryMailEvent.supported_claim_id == stored.claim_id)
    )
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
    with pytest.raises(BadRequestError, match="admitted source evidence"):
        await apply_observation(
            db, organization_id=org.id, observation=observation, mail_event=event
        )
    with pytest.raises(BadRequestError, match="normalized subject"):
        await apply_observation(
            db, organization_id=org.id, observation=observation.model_copy(update={"subject": "."})
        )


async def test_retaining_mail_after_erasing_a_closed_chat_publication(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, owner, _, ctx, grant = await _mail(db)
    store = MemoryService(db)
    first = await _chat_deadline(db, org, owner, "2026-12-01", monkeypatch)
    published = await store.publish_claim(ctx, first, MemoryClaimShare(confirmed=True))
    received = datetime.now(UTC)
    await _admit(db, grant, _delivery("agree", "Deadline: 2026-12-01", received=received))
    await _apply(db, org, ctx, "agree")
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
    org, _, _, ctx, grant = await _mail(db)
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
    await _admit(db, grant, _delivery("contradict", "Deadline: 2026-12-03"))
    assert (await _apply(db, org, ctx, "contradict")).status == "disputed"
    recalled = await claims.recall(db, organization_id=org.id, scopes=[scope], query="XYZ deadline")
    assert [item.id for item in recalled if item.status == "current"] == [first.claim.id]
    assert [item.value for item in recalled if item.status == "disputed"] == ["2026-12-03"]
    assert first.claim.effective_to == now + timedelta(days=1)


async def test_signed_crm_delivery_runs_the_workflow_action(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.workflow_execution import context
    from app.workflows.contracts.results import Completed, Failed
    from app.workflows.nodes.memory_observe import _handler

    org, owner, _ = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    workflow = await _workflow(db, org=org, owner=owner)
    graph = _observation_graph("trigger.webhook")
    exposure_id, secret = await _webhook(db, ctx, workflow, graph)
    body = {
        "record_key": "hubspot:deal/41",
        "object_key": _HANDOFF_KEY,
        "subject": "deadline",
        "value": "2026-12-01",
        "quote": "target_date=2026-12-01",
        "effective_at": "2026-10-04T09:00:00Z",
    }

    async def admit(delivery_id: str, fields: dict[str, str]) -> uuid.UUID:
        encoded = json.dumps(fields).encode()
        admitted = await WorkflowExposureService(db).receive_webhook(
            exposure_id, body=encoded, headers=_signed(secret, encoded, delivery_id)
        )
        return admitted.run_id

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(_handler, "get_worker_db_context", session)
    run_id = await admit("crm-1", body)

    def dispatch(id_: uuid.UUID):
        return context.dispatching_as(
            context.DispatchContext(
                organization_id=org.id,
                workflow_run_id=id_,
                node_run_id=uuid.uuid4(),
                node_instance_id=graph.nodes[-1].id,
                attempt_no=1,
                auth=ctx,
                resumed_agent_run_id=None,
            )
        )

    with dispatch(run_id):
        result = await _handler.handle(_CONFIG, None)
        assert isinstance(result, Completed)
        claim = result.output.claim_id
        assert result.output.status == "applied" and claim is not None
        assert await _handler.handle(_CONFIG, None) == result
    detail = await MemoryService(db).shared_claim_detail(ctx, claim)
    assert [(entry.kind, entry.quote) for entry in detail.evidence] == [
        ("webhook", body["quote"]),
    ]

    store = MemoryService(db)
    await store.update_inbox_rule(
        ctx,
        MemoryInboxRuleUpdate(
            expected_version=0,
            mode="live",
            sources=["webhook"],
            recipient_ids=[owner.id],
        ),
    )
    revision = await admit(
        "crm-revision",
        {
            **body,
            "value": "2026-12-04",
            "quote": "target_date=2026-12-04",
            "effective_at": "2026-10-05T09:00:00Z",
        },
    )
    with dispatch(revision):
        changed = await _handler.handle(_CONFIG, None)
        assert isinstance(changed, Completed) and changed.output.changed
    (delivery,) = await _inbox_jobs(db, org)
    assert await deliver_memory_inbox(db, delivery) == 1
    _, gates, _ = await NotificationCenterService(db).list_inbox(ctx, after=None, limit=10)
    (gate,) = gates.values()
    assert gate.wording_override and gate.wording_override["source"] == "webhook"

    bad = await admit("crm-2", {**body, "object_key": "business:other-company"})
    with dispatch(bad):
        failed = await _handler.handle(_CONFIG, None)
        assert isinstance(failed, Failed) and failed.error.code == "MEMORY_OBSERVATION_REFUSED"


async def test_unfiltered_gmail_run_cannot_claim_source_authority(db: AsyncSession) -> None:
    org, _, _, ctx, grant = await _mail(db, sender=None)
    await _admit(db, grant, _delivery("unfiltered", "Deadline: 2026-12-01"))
    receipt = await _receipt(db, org, "unfiltered")
    assert receipt is not None and receipt.portal_grant_id is None
    with pytest.raises(AuthorizationError, match="full authenticated sender"):
        await _apply(db, org, ctx, "unfiltered")


async def test_workflow_memory_does_not_trust_missing_wrong_or_paused_admissions(
    db: AsyncSession,
) -> None:
    from app.db.models.workflow_exposure import WorkflowExposure

    org, _, _, ctx, grant = await _mail(db)
    await _admit(
        db,
        grant,
        _delivery("valid", "Deadline: cancelled"),
        _delivery("not-an-observation", "Please send through the period"),
        _delivery("future", "Deadline: cancelled", received=datetime.now(UTC) + timedelta(days=2)),
    )
    with pytest.raises(AuthorizationError, match="authorized workflow run"):
        await record_observation(db, auth=ctx, run_id=uuid.uuid4(), config=_CONFIG)
    with pytest.raises(BadRequestError, match="one dated Deadline line"):
        await _apply(db, org, ctx, "not-an-observation")
    with pytest.raises(BadRequestError, match="future"):
        await _apply(db, org, ctx, "future")
    receipt = await _receipt(db, org, "valid")
    assert receipt is not None
    exposure = await db.get(WorkflowExposure, receipt.exposure_id)
    assert exposure is not None
    run = await db.get(WorkflowRun, receipt.workflow_run_id)
    assert run is not None
    original = run.triggered_by
    run.triggered_by = "github"
    await db.flush()
    with pytest.raises(AuthorizationError, match="entry cannot write"):
        await _apply(db, org, ctx, "valid")
    run.triggered_by = original
    exposure.is_active = False
    await db.flush()
    with pytest.raises(AuthorizationError, match="approved trigger is no longer active"):
        await _apply(db, org, ctx, "valid")
    assert await db.scalar(select(MemoryMailEvent.id)) is None


async def test_two_workflows_aggregate_one_gmail_delivery_and_retry_preserves_status(
    db: AsyncSession,
) -> None:
    from app.services.workflow_execution.facade import WorkflowExecutionService

    org, owner, _, ctx, grant = await _mail(db)
    first_delivery = _delivery("first", "Deadline: 2026-12-01")
    await _admit(db, grant, first_delivery)
    assert (await _apply(db, org, ctx, "first")).status == "applied"
    another = await _workflow(db, org=org, owner=owner)
    await _publish(
        db,
        ctx,
        another,
        _observation_graph("trigger.gmail", {"sender_contains": "desk@example.org"}),
    )

    change = _delivery("next", "Deadline: cancelled")
    await _admit(db, grant, change)
    receipts = list(
        await db.scalars(
            select(WorkflowWebhookDelivery)
            .where(
                WorkflowWebhookDelivery.organization_id == org.id,
                WorkflowWebhookDelivery.delivery_id == "gmail:next",
            )
            .order_by(WorkflowWebhookDelivery.id)
        )
    )
    assert len(receipts) == 2
    original = await record_observation(
        db, auth=ctx, run_id=receipts[0].workflow_run_id, config=_CONFIG
    )
    assert original.status == "changed"
    other = await record_observation(
        db, auth=ctx, run_id=receipts[1].workflow_run_id, config=_CONFIG
    )
    assert other.status == "duplicate" and other.claim_id == original.claim_id and not other.changed
    run = await db.get(WorkflowRun, receipts[0].workflow_run_id)
    assert run is not None
    run.status = "failed"
    await db.flush()
    retried = await WorkflowExecutionService(db).retry(ctx, run.id)
    assert await record_observation(db, auth=ctx, run_id=retried.id, config=_CONFIG) == original
    clone = await db.get(WorkflowRun, retried.id)
    assert clone is not None
    clone.retry_of_run_id = receipts[1].workflow_run_id
    await db.flush()
    with pytest.raises(BadRequestError, match="original delivery is unavailable"):
        await record_observation(db, auth=ctx, run_id=clone.id, config=_CONFIG)
    clone.retry_of_run_id = None
    await db.flush()
    with pytest.raises(BadRequestError, match="admitted Gmail or signed webhook"):
        await record_observation(db, auth=ctx, run_id=clone.id, config=_CONFIG)


async def test_memory_workflow_validate_publish_permissions_and_properties(
    db: AsyncSession,
) -> None:
    from app.workflows.contracts.results import Failed
    from app.workflows.nodes.memory_observe import _handler

    org, owner, reader = await _org(db)
    editor = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    assert await _handler.check_resources(db, editor, _CONFIG) == []
    assert (await _handler.check_resources(db, viewer, _CONFIG))[0][0] == "object_key"
    with pytest.raises(ValueError, match="Choose a valid business property"):
        MemoryObservationConfig.model_validate({**_CONFIG.model_dump(), "subject": "."})
    assert isinstance(await _handler.handle(None, None), Failed)


async def _inbox_jobs(db: AsyncSession, org: Organization) -> list[DeliverMemoryInbox]:
    jobs = await db.scalars(
        select(BackgroundJob)
        .where(
            BackgroundJob.organization_id == org.id, BackgroundJob.kind == DELIVER_MEMORY_INBOX.kind
        )
        .order_by(BackgroundJob.created_at, BackgroundJob.run_after)
    )
    return [DeliverMemoryInbox.model_validate(row.payload) for row in jobs]


async def test_workflow_memory_inbox_shadow_live_cancellation_and_revocation(
    db: AsyncSession,
) -> None:
    org, owner, reader, ctx, grant = await _mail(db)
    store = MemoryService(db)
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    initial = await store.inbox_rule(ctx)
    assert initial.version == 0 and initial.mode == "off"
    draft = MemoryInboxRuleUpdate(
        expected_version=0,
        mode="shadow",
        sources=["gmail"],
        recipient_ids=[owner.id, reader.id],
    )
    with pytest.raises(AuthorizationError):
        await store.update_inbox_rule(viewer, draft)
    with pytest.raises(BadRequestError, match="active organization members"):
        await store.update_inbox_rule(
            ctx, draft.model_copy(update={"recipient_ids": [uuid.uuid4()]})
        )
    shadow = await store.update_inbox_rule(ctx, draft)
    with pytest.raises(ConflictError):
        await store.update_inbox_rule(ctx, draft)

    now = datetime.now(UTC)
    await _admit(
        db,
        grant,
        _delivery("inbox-a", "Deadline: 2026-12-01", received=now - timedelta(minutes=6)),
        _delivery("inbox-b", "Deadline: 2026-12-03", received=now - timedelta(minutes=5)),
        _delivery("inbox-same", "Deadline: 2026-12-03", received=now - timedelta(minutes=4)),
        _delivery("inbox-cancel", "Deadline: cancelled", received=now - timedelta(minutes=3)),
        _delivery("inbox-c", "Deadline: 2026-12-15", received=now - timedelta(minutes=2)),
    )
    await _apply(db, org, ctx, "inbox-a")
    assert await _inbox_jobs(db, org) == []
    await _apply(db, org, ctx, "inbox-b")
    await _apply(db, org, ctx, "inbox-same")
    (job,) = await _inbox_jobs(db, org)
    assert job.change == "changed"
    assert await deliver_memory_inbox(db, job) == 0
    assert await deliver_memory_inbox(db, job) == 0
    results = await store.inbox_decision_counts(ctx, shadow.version)
    assert [(row.change, row.outcome, row.count) for row in results] == [("changed", "shadow", 2)]
    center = NotificationCenterService(db)
    assert (await center.list_inbox(ctx, after=None, limit=10))[0] == []

    active = await store.update_inbox_rule(
        ctx,
        draft.model_copy(update={"expected_version": shadow.version, "mode": "live"}),
    )
    assert await store.inbox_rule(ctx) == active
    await _apply(db, org, ctx, "inbox-cancel")
    cancel = next(job for job in await _inbox_jobs(db, org) if job.change == "cancelled")
    assert cancel.rule_version == active.version
    assert await deliver_memory_inbox(db, cancel) == 2
    assert await deliver_memory_inbox(db, cancel) == 0
    assert await deliver_memory_inbox(db, job) == 0
    cards, gates, _ = await center.list_inbox(viewer, after=None, limit=10)
    assert len(cards) == 1
    card = cards[0]
    assert card.event_type == NotificationEventType.MEMORY_DEADLINE_CHANGE
    assert card.render_context is not None and "before" not in card.render_context
    gate = gates[card.id]
    visible = NotificationRead.from_row(
        card,
        strip_context_url=gate.strip_context_url,
        summary_override=gate.summary_override,
        wording_override=gate.wording_override,
    )
    assert visible.wording_params is not None
    assert visible.wording_params["before"] == "2026-12-03"
    assert visible.wording_params["after"] == ""
    assert visible.wording_params["source"] == "gmail"
    assert card.context_url and card.context_url.startswith(
        "/settings/memory?library=organization&object="
    )
    # Even after normal Inbox retention removes the row, the delivery receipt survives.
    await db.delete(card)
    await db.flush()
    assert await deliver_memory_inbox(db, cancel) == 0

    owner.is_active = False
    await db.flush()
    assert (await center.list_inbox(ctx, after=None, limit=10))[0] == []
    owner.is_active = True
    await db.flush()
    await _apply(db, org, ctx, "inbox-c")
    newest = next(
        pending
        for pending in await _inbox_jobs(db, org)
        if pending.claim_id not in (cancel.claim_id, job.claim_id)
    )
    grant.authorization_generation = uuid.uuid4()
    await db.flush()
    assert await deliver_memory_inbox(db, newest) == 0
    assert (await center.list_inbox(ctx, after=None, limit=10))[0] == []
    assert (
        len(
            list(
                await db.scalars(select(Notification).where(Notification.organization_id == org.id))
            )
        )
        == 1
    )


async def test_merge_timeline_keeps_evidence_and_is_reversible(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    viewer = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    store = MemoryService(db)
    scope = ClaimScope(organization_owner_key(org.id))

    async def remember(name: str, key: str, statement: str) -> MemoryClaim:
        return (
            await claims.remember(
                db,
                organization_id=org.id,
                scope=scope,
                statement=statement,
                object_ref=MemoryObjectRef(kind="company", name=name, external_key=key),
            )
        ).claim

    canonical = await remember("Atlas", "crm:atlas", "Canonical claim")
    alias = await remember("Atlas LLC", "erp:atlas", "Alias claim")
    third = await remember("Atlas Group", "crm:atlas-group", "Unrelated claim")
    assert canonical.object_id and alias.object_id and third.object_id
    target, source = canonical.object_id, alias.object_id
    review = MemoryObjectMergeCreate(source_id=source, confirmed=True)
    with pytest.raises(AuthorizationError):
        await store.merge_objects(viewer, library="organization", target_id=target, data=review)
    with pytest.raises(BadRequestError):
        await store.merge_objects(
            ctx,
            library="organization",
            target_id=source,
            data=review,
        )

    merged = await store.merge_objects(ctx, library="organization", target_id=target, data=review)
    with pytest.raises(ConflictError):
        await store.merge_objects(
            ctx,
            library="organization",
            target_id=third.object_id,
            data=review,
        )
    recorded = await store.object_merges(
        ctx, library="organization", target_id=target, cursor=None, limit=10
    )
    candidates = await store.objects(
        ctx,
        library="organization",
        kind=None,
        q="",
        cursor=None,
        limit=10,
        merge_target=target,
    )
    assert [(item.id, item.external_key) for item in candidates.items] == [
        (third.object_id, "crm:atlas-group"),
    ]
    assert [row.source.id for row in recorded.items] == [source]
    more = await remember("Atlas LLC", "erp:atlas", "Filed after merge")
    page = await store.objects(
        ctx, library="organization", kind="company", q="Atlas LLC", cursor=None, limit=10
    )
    assert [entity.id for entity in page.items] == [target]

    async def timeline(object_id: uuid.UUID, cursor: uuid.UUID | None = None, limit: int = 10):
        return await store.object_timeline(
            viewer,
            library="organization",
            object_id=object_id,
            as_of=None,
            known_at=None,
            cursor=cursor,
            limit=limit,
        )

    page_one = await timeline(source, limit=1)
    assert page_one.object.id == target and page_one.next_cursor
    page_two = await timeline(target, cursor=page_one.next_cursor)
    assert {row.id for row in page_one.items + page_two.items} == {canonical.id, alias.id, more.id}
    assert more.object_id == source
    await store.undo_object_merge(ctx, library="organization", target_id=target, merge_id=merged.id)
    assert {row.id for row in (await timeline(source)).items} == {alias.id, more.id}
    assert [row.id for row in (await timeline(target)).items] == [canonical.id]
    with pytest.raises(NotFoundError):
        await store.undo_object_merge(
            ctx, library="organization", target_id=target, merge_id=merged.id
        )


async def test_backfill_resumes_and_links_only_exact_same_scope_lineage(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    store = MemoryService(db)
    scope = ClaimScope(person_owner_key(owner.id))
    original = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            subject="status",
            statement="Atlas is active",
            object_ref=MemoryObjectRef(kind="company", name="Atlas", external_key="crm:atlas"),
        )
    ).claim
    exact = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=scope.scope_key,
        subject="status",
        supersedes_id=original.id,
        statement="Updated Atlas status",
        created_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    other_scope = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=person_owner_key(reader.id),
        subject="status",
        derived_from=[str(original.id)],
        statement="Updated Atlas status",
        created_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    name_only = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=scope.scope_key,
        subject="status",
        statement=original.statement,
    )

    two = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=scope,
            statement="Atlas VC is active",
            subject="status",
            object_ref=MemoryObjectRef(
                kind="company", name="Atlas VC", external_key="crm:atlas-vc"
            ),
        )
    ).claim
    ambiguous = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=scope.scope_key,
        subject="status",
        derived_from=[str(original.id), str(two.id)],
        statement="Which Atlas?",
    )
    malformed = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=scope.scope_key,
        derived_from=["legacy-event"],
        statement="Malformed lineage",
    )
    extensive = await memory_claim.create(
        db,
        organization_id=org.id,
        scope_key=scope.scope_key,
        subject="status",
        derived_from=[str(original.id)] * 101,
        statement="Unbounded lineage",
    )
    assert await store.object_backfill_status(ctx) is None
    with pytest.raises(AuthorizationError):
        await store.advance_object_backfill(
            AuthContext(user_id=reader.id, organization_id=org.id, role="viewer"),
            MemoryObjectBackfillAdvance(limit=1),
        )
    first = await store.advance_object_backfill(ctx, MemoryObjectBackfillAdvance(limit=1))
    assert (first.scanned, first.linked, first.completed_at) == (1, 1, None)
    assert await MemoryService(db).object_backfill_status(ctx) == first
    last = await MemoryService(db).advance_object_backfill(
        ctx, MemoryObjectBackfillAdvance(limit=10)
    )
    assert (last.scanned, last.linked) == (6, 1)
    assert last.completed_at is not None
    assert await store.advance_object_backfill(ctx, MemoryObjectBackfillAdvance()) == last
    await db.refresh(exact)
    assert exact.object_id == original.object_id
    assert exact.updated_at is None
    assert all(
        row.object_id is None for row in (other_scope, name_only, ambiguous, malformed, extensive)
    )
    assert exact.supersedes_id == original.id and exact.statement == "Updated Atlas status"
    assert await _inbox_jobs(db, org) == []


async def test_backfill_worker_uses_committed_cursor_and_fences_old_owner(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, owner, reader = await _org(db)
    operator = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    reader_id = reader.id
    store = MemoryService(db)

    @asynccontextmanager
    async def current_db():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", current_db)
    await db.execute(
        insert(MemoryClaim),
        [
            {
                "organization_id": org.id,
                "scope_key": person_owner_key(owner.id),
                "statement": f"Legacy claim {i}",
            }
            for i in range(201)
        ],
    )
    state = await store.run_object_backfill(operator, MemoryObjectBackfillRun())
    assert (state.scanned, state.linked, state.completed_at) == (0, 0, None)
    with pytest.raises(ConflictError):
        await store.run_object_backfill(operator, MemoryObjectBackfillRun(restart=True))
    await store.run_object_backfill(operator, MemoryObjectBackfillRun())

    async def take_job() -> BackfillMemoryObjects:
        row = (
            await db.execute(
                select(BackgroundJob).where(
                    BackgroundJob.organization_id == org.id,
                    BackgroundJob.kind == BACKFILL_MEMORY_OBJECTS.kind,
                    BackgroundJob.status == "queued",
                )
            )
        ).scalar_one()
        row.status = "running"
        await db.flush()
        return BackfillMemoryObjects.model_validate(row.payload)

    first = await take_job()
    assert await memory_tasks.backfill_memory_objects(first) == 200
    running = await db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.organization_id == org.id,
            BackgroundJob.kind == BACKFILL_MEMORY_OBJECTS.kind,
            BackgroundJob.status == "running",
        )
    )
    assert running is not None
    running.status = "succeeded"
    await db.flush()
    following = await take_job()
    assert first.cutoff == following.cutoff
    assert (
        await memory_tasks.backfill_memory_objects(
            following.model_copy(update={"requested_by": reader_id}),
        )
        == 0
    )
    status = await store.object_backfill_status(operator)
    assert status is not None and status.scanned == 200 and status.completed_at is None
    assert await memory_tasks.backfill_memory_objects(following) == 1
    done = await store.object_backfill_status(operator)
    assert done is not None and done.scanned == 201 and done.completed_at is not None
    assert await store.run_object_backfill(operator, MemoryObjectBackfillRun()) == done
    empty, empty_owner, _ = await _org(db)
    empty_ctx = AuthContext(user_id=empty_owner.id, organization_id=empty.id, role="owner")
    no_rows = await store.advance_object_backfill(empty_ctx, MemoryObjectBackfillAdvance())
    assert no_rows.completed_at is not None and no_rows.scanned == 0
    new = await store.run_object_backfill(operator, MemoryObjectBackfillRun(restart=True))
    assert new.cutoff > first.cutoff and new.scanned == 0
    assert await memory_tasks.backfill_memory_objects(following) == 0


async def test_inbox_rechecks_group_access_before_delivery_and_read(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    operator = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    watcher = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    store = MemoryService(db)
    draft = MemoryInboxRuleUpdate(
        expected_version=0,
        mode="live",
        recipient_ids=[reader.id],
        sources=["reviewed"],
        include_review=True,
    )
    await store.update_inbox_rule(operator, draft)
    group = Group(organization_id=org.id, name="Sales")
    db.add(group)
    await db.flush()
    seats = [
        GroupMember(group_id=group.id, user_id=owner.id),
        GroupMember(group_id=group.id, user_id=reader.id),
    ]
    db.add_all(seats)
    await db.flush()
    scope = ClaimScope(f"group:{group.id}")
    ref = MemoryObjectRef(kind="commitment", name="Sales handoff", external_key="crm:handoff")

    async def remember(value: str, *, reviewed: bool = True) -> MemoryClaim:
        return (
            await claims.remember(
                db,
                organization_id=org.id,
                scope=scope,
                object_ref=ref,
                subject="deadline",
                value=value,
                statement=f"Deadline: {value}",
                origin="person" if reviewed else "agent",
                author_user_id=owner.id if reviewed else None,
                reviewed_publication=reviewed,
            )
        ).claim

    first = await remember("2026-12-01")
    update = await remember("2026-12-02")
    (job,) = await _inbox_jobs(db, org)
    assert job.claim_id == update.id and job.previous_id == first.id
    assert await deliver_memory_inbox(db, job) == 1
    center = NotificationCenterService(db)
    assert len((await center.list_inbox(watcher, after=None, limit=10))[0]) == 1
    await db.delete(seats[1])
    await db.flush()
    assert (await center.list_inbox(watcher, after=None, limit=10))[0] == []
    assert (await center.unread_count(watcher)).count == 0
    denied = await remember("2026-12-03")
    second = next(job for job in await _inbox_jobs(db, org) if job.claim_id == denied.id)
    assert await deliver_memory_inbox(db, second) == 0


async def test_inbox_sends_review_then_accepted_change_for_one_claim(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, owner, reader, ctx, grant = await _mail(db)
    store = MemoryService(db)
    rule = await store.update_inbox_rule(
        ctx,
        MemoryInboxRuleUpdate(
            expected_version=0,
            mode="live",
            sources=["reviewed"],
            recipient_ids=[reader.id],
            include_review=True,
        ),
    )
    await _admit(db, grant, _delivery("paired-inbox", "Deadline: 2026-12-01"))
    await _apply(db, org, ctx, "paired-inbox")
    private = await _chat_deadline(db, org, owner, "2026-12-02", monkeypatch)
    disputed = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    (needs_review,) = await _inbox_jobs(db, org)
    assert (needs_review.change, needs_review.claim_id) == ("review", disputed.id)

    @asynccontextmanager
    async def current_db():
        yield db

    monkeypatch.setattr(memory_tasks, "get_db_context", current_db)
    assert await memory_tasks.notify_memory_change(needs_review) == 1
    detail = await store.shared_claim_detail(ctx, disputed.id)
    await store.resolve_shared_conflict(
        ctx,
        disputed.id,
        MemoryConflictResolve(candidate_ids=[row.id for row in detail.conflicts]),
    )
    change = next(job for job in await _inbox_jobs(db, org) if job.change == "changed")
    assert (
        change.claim_id == needs_review.claim_id and change.revision_at > needs_review.revision_at
    )
    assert await deliver_memory_inbox(db, needs_review) == 0
    assert await deliver_memory_inbox(db, change) == 1
    counts = await store.inbox_decision_counts(ctx, rule.version)
    assert [(row.change, row.outcome, row.count) for row in counts] == [
        ("changed", "delivered", 1),
        ("review", "delivered", 1),
    ]


async def test_policy_skips_non_deadline_changes_and_survives_inbox_mute(db: AsyncSession) -> None:
    org, owner, reader = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    store = MemoryService(db)
    center = NotificationCenterService(db)
    reader_ctx = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    rule_data = MemoryInboxRuleUpdate(
        expected_version=0,
        mode="live",
        sources=["reviewed"],
        recipient_ids=[reader.id],
    )
    with pytest.raises(BadRequestError, match="at least one"):
        await store.update_inbox_rule(ctx, rule_data.model_copy(update={"recipient_ids": []}))
    rule = await store.update_inbox_rule(ctx, rule_data)
    scope = ClaimScope(organization_owner_key(org.id))

    async def record(
        value: str, *, object_kind: MemoryObjectKind = "commitment", accepted: bool = True
    ):
        # Both reviewed and unreviewed changes may be observed, but only sources
        # approved by the organization rule can produce a card.
        ref = MemoryObjectRef(kind=object_kind, name="Atlas")
        return (
            await claims.remember(
                db,
                organization_id=org.id,
                scope=scope,
                object_ref=ref,
                value=value,
                statement=f"Observed {value}",
                subject="deadline",
                origin="person" if accepted else "agent",
                corrects=not accepted,
                author_user_id=owner.id if accepted else None,
            )
        ).claim

    await record("2026-12-01")
    await record("2026-W09-1")
    await record("2026-02-31")
    await record("2026-12-02")
    await record("2026-12-03", accepted=False)
    assert await _inbox_jobs(db, org) == []

    await record("2026-12-01", object_kind="company")
    unrelated = await record("2026-12-02", object_kind="company")
    muted = await record("2026-12-04")
    jobs = {job.claim_id: job for job in await _inbox_jobs(db, org)}
    assert await deliver_memory_inbox(db, jobs[unrelated.id]) == 0
    assert (
        await deliver_memory_inbox(db, jobs[muted.id].model_copy(update={"policy_version": 0})) == 0
    )
    await center.update_preference(
        reader_ctx,
        event_type=NotificationEventType.MEMORY_DEADLINE_CHANGE,
        channel=NotificationChannel.IN_APP,
        enabled=False,
    )
    assert await deliver_memory_inbox(db, jobs[muted.id]) == 0
    assert (await center.list_inbox(reader_ctx, after=None, limit=10))[0] == []
    counts = await store.inbox_decision_counts(ctx, rule.version)
    assert [(row.change, row.outcome, row.count) for row in counts] == [("changed", "muted", 1)]

    newer = await record("2026-12-05")
    pending = next(job for job in await _inbox_jobs(db, org) if job.claim_id == newer.id)
    await memory_claim.set_status(
        db, newer, "current", effective_to=datetime.now(UTC) + timedelta(days=1)
    )
    assert await deliver_memory_inbox(db, pending) == 0
    assert await store.inbox_decision_counts(ctx, rule.version) == counts


async def test_inbox_checks_the_still_authorized_source_at_delivery(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, owner, reader, ctx, grant = await _mail(db)
    store = MemoryService(db)
    await store.update_inbox_rule(
        ctx,
        MemoryInboxRuleUpdate(
            expected_version=0,
            mode="live",
            sources=["gmail"],
            recipient_ids=[reader.id],
        ),
    )
    await _admit(
        db,
        grant,
        _delivery("scope-a", "Deadline: 2026-12-01"),
        _delivery("scope-b", "Deadline: 2026-12-02"),
    )
    await _apply(db, org, ctx, "scope-a")
    await _apply(db, org, ctx, "scope-b")
    (job,) = await _inbox_jobs(db, org)
    private = await _chat_deadline(db, org, owner, "2026-12-02", monkeypatch)
    shared = await store.publish_claim(ctx, private, MemoryClaimShare(confirmed=True))
    assert shared.id == job.claim_id
    invalid_proof = job.model_copy(update={"source_event_id": uuid.uuid4()})
    assert await deliver_memory_inbox(db, invalid_proof) == 0
    assert await deliver_memory_inbox(db, job) == 1
    assert await deliver_memory_inbox(db, job) == 0
    member = AuthContext(user_id=reader.id, organization_id=org.id, role="viewer")
    center = NotificationCenterService(db)
    _, gates, _ = await center.list_inbox(member, after=None, limit=10)
    (gate,) = gates.values()
    assert gate.wording_override and gate.wording_override["source"] == "gmail"
    grant.is_enabled = False
    await db.flush()
    assert (await center.list_inbox(member, after=None, limit=10))[0] == []


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("replacement", [None, 0, False, "2026-12-04"])
async def test_corrections_preserve_or_replace_typed_values(
    db: AsyncSession, historical: bool, replacement: int | bool | str | None
) -> None:
    org, owner, _ = await _org(db)
    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1) if historical else None
    original = (
        await claims.remember(
            db,
            organization_id=org.id,
            scope=ClaimScope(person_owner_key(owner.id)),
            statement="Atlas headcount was 20",
            object_ref=MemoryObjectRef(kind="company", name="Atlas"),
            subject="headcount",
            value=20,
            effective_from=start,
            effective_to=end,
        )
    ).claim

    new = await MemoryService(db).correct_claim(
        ctx,
        original.id,
        MemoryClaimCorrect(
            statement="Corrected Atlas observation", historical=historical, value=replacement
        ),
    )

    expected = 20 if replacement is None else replacement
    assert type(new.value) is type(expected)
    assert new.value == expected
    assert original.value == 20 and new.object_id == original.object_id
    assert new.supersedes_id == original.id
    if historical:
        assert (new.effective_from, new.effective_to) == (start, end)


async def test_external_identity_can_rename_without_losing_claim_links(db: AsyncSession) -> None:
    org, owner, _ = await _org(db)
    personal, shared = person_owner_key(owner.id), organization_owner_key(org.id)
    ref = MemoryObjectRef(kind="company", name="Atlas", external_key="crm:atlas")
    private_fact = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(personal),
        object_ref=ref,
        statement="Atlas renewed",
    )
    old = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(shared),
        object_ref=ref,
        statement="Atlas renewed",
    )
    # Keep the original ORM row in the session so RETURNING has to refresh it.
    old_obj = await memory_claim.get_object(
        db,
        organization_id=org.id,
        scope_keys=[shared],
        object_id=old.claim.object_id,
    )
    assert old_obj is not None and old_obj.name == "Atlas"
    new = await claims.remember(
        db,
        organization_id=org.id,
        scope=ClaimScope(shared),
        object_ref=ref.model_copy(update={"name": "Atlas Group"}),
        statement="Atlas Group renewed",
    )
    assert new.claim.object_id == old_obj.id == old.claim.object_id
    assert old_obj.name == "Atlas Group"

    ctx = AuthContext(user_id=owner.id, organization_id=org.id, role="owner")
    store = MemoryService(db)
    await store.publish_claim(ctx, private_fact.claim.id, MemoryClaimShare(confirmed=True))
    assert old_obj.name == "Atlas Group"  # A copy with the old label cannot undo the rename.
    page = await store.objects(
        ctx, library="organization", kind="company", q="Atlas Group", cursor=None, limit=10
    )
    assert [(obj.id, obj.name) for obj in page.items] == [(old_obj.id, "Atlas Group")]
