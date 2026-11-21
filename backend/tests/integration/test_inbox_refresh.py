"""Atomic replacement of generated Inbox proposals, against real PostgreSQL."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.mcp_connection import McpConnection
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.outcome import Outcome
from app.db.models.suggestion import Suggestion, SuggestionStatus
from app.db.models.user import User
from app.repositories import suggestion_repo, watch_repo
from app.services.suggestions import SuggestionService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass(frozen=True)
class People:
    organization_id: UUID
    other_organization_id: UUID
    user_id: UUID
    colleague_id: UUID


async def _people(db: AsyncSession) -> People:
    users = [User(email=f"{uuid.uuid4()}@example.com", hashed_password="x") for _ in range(2)]
    db.add_all(users)
    await db.flush()
    orgs = [
        Organization(name="Inbox", slug=uuid.uuid4().hex, created_by_user_id=users[0].id)
        for _ in range(2)
    ]
    db.add_all(orgs)
    await db.flush()
    db.add_all(
        OrganizationMember(organization_id=org.id, user_id=user.id, role="member")
        for org in orgs
        for user in users
    )
    await db.flush()
    return People(orgs[0].id, orgs[1].id, users[0].id, users[1].id)


async def _proposal(
    db: AsyncSession,
    people: People,
    *,
    kind: str = "agent",
    status: SuggestionStatus = SuggestionStatus.OPEN,
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
    watch_id: UUID | None = None,
    outcome_id: UUID | None = None,
) -> Suggestion:
    row = await suggestion_repo.propose(
        db,
        organization_id=organization_id or people.organization_id,
        user_id=user_id or people.user_id,
        kind=kind,
        title="A generated proposal",
        detail="A recurring request",
        payload={"request": "Prepare the weekly report"},
        dedupe_key=uuid.uuid4().hex,
        watch_id=watch_id,
    )
    assert row is not None
    if status != SuggestionStatus.OPEN:
        await suggestion_repo.decide(db, suggestion=row, status=status)
    if outcome_id:
        await suggestion_repo.link_outcome(db, suggestion=row, outcome_id=outcome_id)
    return row


async def _links(db: AsyncSession, people: People) -> tuple[UUID, UUID]:
    connection = McpConnection(
        scope="user",
        user_id=people.user_id,
        name="GitHub",
        catalog_key="github",
        url="https://mcp.example.com/mcp",
        secret_key_version=1,
    )
    db.add(connection)
    await db.flush()
    watch = await watch_repo.create(
        db,
        organization_id=people.organization_id,
        user_id=people.user_id,
        connection_id=connection.id,
        preset_key=None,
        title="Reviews",
        instructions="Find pending reviews",
        urgent=False,
        interval_minutes=60,
        next_run_at=datetime.now(UTC),
    )
    outcome = Outcome(
        organization_id=people.organization_id,
        user_id=people.user_id,
        kind="finding",
        dedupe_key=uuid.uuid4().hex,
        summary="A linked case",
    )
    db.add(outcome)
    await db.flush()
    return watch.id, outcome.id


async def _ids(db: AsyncSession) -> set[UUID]:
    return set((await db.scalars(select(Suggestion.id))).all())


async def test_candidate_counts_exclude_decisions_findings_and_linked_cases(
    db: AsyncSession,
) -> None:
    people = await _people(db)
    assert (
        await suggestion_repo.open_generated_people(db, organization_id=people.organization_id)
        == {}
    )
    for kind in ("agent", "routine", "profile", "role_pack"):
        await _proposal(db, people, kind=kind)
    for _ in range(2):
        await _proposal(db, people, user_id=people.colleague_id)
    await _proposal(db, people, organization_id=people.other_organization_id)
    await _proposal(db, people, status=SuggestionStatus.ACCEPTED)
    await _proposal(db, people, status=SuggestionStatus.DISMISSED)
    await _proposal(db, people, kind="finding")
    watch_id, outcome_id = await _links(db, people)
    await _proposal(db, people, watch_id=watch_id)
    await _proposal(db, people, outcome_id=outcome_id)
    assert await suggestion_repo.open_generated_people(
        db, organization_id=people.organization_id
    ) == {
        people.user_id: 4,
        people.colleague_id: 2,
    }
    assert await suggestion_repo.open_generated_people(
        db, organization_id=people.other_organization_id
    ) == {
        people.user_id: 1,
    }


async def test_removes_only_the_captured_persons_open_generated_rows(db: AsyncSession) -> None:
    people = await _people(db)
    captured = {(await _proposal(db, people)).id, (await _proposal(db, people, kind="routine")).id}
    later = await _proposal(db, people)
    colleague = await _proposal(db, people, user_id=people.colleague_id)
    elsewhere = await _proposal(db, people, organization_id=people.other_organization_id)
    finding = await _proposal(db, people, kind="finding")
    assert (
        await suggestion_repo.remove_open_generated(
            db,
            organization_id=people.organization_id,
            user_id=people.user_id,
            expected_ids=captured,
        )
        is True
    )
    assert await _ids(db) == {later.id, colleague.id, elsewhere.id, finding.id}


@pytest.mark.parametrize(
    "protected",
    ["accepted", "dismissed", "finding", "watch", "outcome", "organization", "user", "missing"],
)
async def test_any_ineligible_snapshot_row_refuses_the_whole_replacement(
    db: AsyncSession, protected: str
) -> None:
    people = await _people(db)
    replaceable = await _proposal(db, people)
    watch_id, outcome_id = await _links(db, people)
    if protected == "missing":
        blocked_id = uuid.uuid4()
    else:
        blocked = await _proposal(
            db,
            people,
            status=SuggestionStatus(protected)
            if protected in {"accepted", "dismissed"}
            else SuggestionStatus.OPEN,
            kind="finding" if protected == "finding" else "agent",
            watch_id=watch_id if protected == "watch" else None,
            outcome_id=outcome_id if protected == "outcome" else None,
            organization_id=people.other_organization_id if protected == "organization" else None,
            user_id=people.colleague_id if protected == "user" else None,
        )
        blocked_id = blocked.id
    before = await _ids(db)
    assert (
        await suggestion_repo.remove_open_generated(
            db,
            organization_id=people.organization_id,
            user_id=people.user_id,
            expected_ids={replaceable.id, blocked_id},
        )
        is False
    )
    await db.flush()
    assert await _ids(db) == before


@pytest.mark.parametrize("decision", ["accepted", "deleted"])
async def test_reloads_cached_rows_after_a_concurrent_decision_or_deletion(
    db: AsyncSession,
    engine: AsyncEngine,
    decision: str,
) -> None:
    people = await _people(db)
    first = await _proposal(db, people)
    second = await _proposal(db, people)
    first_id, second_id = first.id, second.id
    await db.commit()
    assert first.status == "open"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as concurrent:
        changed = await concurrent.get(Suggestion, first_id)
        assert changed is not None
        if decision == "deleted":
            await concurrent.delete(changed)
        else:
            await suggestion_repo.decide(
                concurrent, suggestion=changed, status=SuggestionStatus.ACCEPTED
            )
        await concurrent.commit()
    # The original identity-map instance is deliberately stale, as after a model call.
    assert first.status == "open"
    assert (
        await suggestion_repo.remove_open_generated(
            db,
            organization_id=people.organization_id,
            user_id=people.user_id,
            expected_ids={first_id, second_id},
        )
        is False
    )
    if decision == "accepted":
        assert first.status == "accepted"
    await db.flush()
    await db.commit()
    async with factory() as verification:
        rows = dict((await verification.execute(select(Suggestion.id, Suggestion.status))).all())
        expected = {second_id: "open"}
        if decision == "accepted":
            expected[first_id] = "accepted"
        assert rows == expected


async def test_a_failed_new_record_rolls_back_removal_and_restores_old_proposals(
    db: AsyncSession,
) -> None:
    people = await _people(db)
    old = await _proposal(db, people)
    old_id = old.id
    await db.commit()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            assert (
                await suggestion_repo.remove_open_generated(
                    db,
                    organization_id=people.organization_id,
                    user_id=people.user_id,
                    expected_ids={old_id},
                )
                is True
            )
            assert await _ids(db) == set()
            replacement = await _proposal(db, people, kind="routine")
            assert await _ids(db) == {replacement.id}
            await _proposal(db, people, kind="invalid-kind")
    assert await _ids(db) == {old_id}
    restored = await db.get(Suggestion, old_id)
    assert restored is not None
    assert restored.status == "open"


async def _observe_row_wait(engine: AsyncEngine, pid: int, operation: asyncio.Task[bool]) -> bool:
    async with engine.connect() as connection:
        observer = await connection.execution_options(isolation_level="AUTOCOMMIT")
        while not operation.done():
            result = await observer.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            )
            if result.scalar_one_or_none() == "Lock":
                return True
            await asyncio.sleep(0.01)
    return False


@pytest.mark.parametrize("decision", ["accept", "dismiss"])
async def test_a_decision_claims_the_card_before_refresh_can_replace_it(
    db: AsyncSession, engine: AsyncEngine, decision: str
) -> None:
    people = await _people(db)
    row = await _proposal(db, people, kind="profile" if decision == "accept" else "routine")
    row.payload = {"job_title": "Team lead"}
    identifier = row.id
    await db.commit()
    started, release = asyncio.Event(), asyncio.Event()

    class PausingDecision(SuggestionService):
        async def _own_open(self, ctx: AuthContext, suggestion_id: UUID) -> Suggestion:
            claimed = await super()._own_open(ctx, suggestion_id)
            started.set()
            await release.wait()
            return claimed

    context = AuthContext(
        user_id=people.user_id,
        organization_id=people.organization_id,
        role=OrgRoleName.MEMBER,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def answer() -> str:
        async with factory() as session:
            service = PausingDecision(session)
            answered = (
                await service.accept(context, identifier)
                if decision == "accept"
                else await service.dismiss(context, identifier)
            )
            await session.commit()
            return answered.status

    async with factory() as refresh_session:
        pid = (await refresh_session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        assert isinstance(pid, int)

        async def replace() -> bool:
            removed = await suggestion_repo.remove_open_generated(
                refresh_session,
                organization_id=people.organization_id,
                user_id=people.user_id,
                expected_ids={identifier},
            )
            await refresh_session.commit()
            return removed

        answering = asyncio.create_task(answer())
        replacing: asyncio.Task[bool] | None = None
        observing: asyncio.Task[bool] | None = None
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            replacing = asyncio.create_task(replace())
            observing = asyncio.create_task(_observe_row_wait(engine, pid, replacing))
            blocked = await asyncio.wait_for(observing, timeout=5)
            assert blocked, "Refresh must wait for the in-progress user decision"
            release.set()
            status = await asyncio.wait_for(answering, timeout=5)
            removed = await asyncio.wait_for(replacing, timeout=5)
            assert status == ("accepted" if decision == "accept" else "dismissed")
            assert removed is False
        finally:
            release.set()
            await asyncio.gather(
                answering,
                *(task for task in (replacing, observing) if task is not None),
                return_exceptions=True,
            )
    async with factory() as verification:
        saved = await verification.get(Suggestion, identifier)
        assert saved is not None
        assert saved.status == status
        if decision == "accept":
            person = await verification.get(User, people.user_id)
            assert person is not None
            assert person.job_title == "Team lead"


async def test_finding_reads_keep_the_case_services_lock_order(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    people = await _people(db)
    finding = await _proposal(db, people, kind="finding")
    identifier = finding.id
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as holding, factory() as reading:
        await holding.execute(
            select(Suggestion).where(Suggestion.id == identifier).with_for_update()
        )
        found = await asyncio.wait_for(
            suggestion_repo.get_own(
                reading,
                identifier,
                organization_id=people.organization_id,
                user_id=people.user_id,
                lock_generated=True,
            ),
            timeout=2,
        )
        assert found is not None
        assert found.kind == "finding"
