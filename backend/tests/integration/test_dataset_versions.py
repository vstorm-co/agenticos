"""What a dataset version holds, against Postgres, now that it is kept on the revisions.

The claims a mocked session cannot make:

- after every kind of change - an add, an import, accepted drafts, an edit, a
  removal - every earlier version still reads exactly what it read before:
  the same revisions in the same order, found the same way;
- a version's cases page, filter and place the same way an older version's do;
- a change stores only what it changed, and closes nothing an earlier version holds;
- two changes made at once to one dataset become two consecutive versions whose
  holdings do not overlap.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.dataset import DatasetCase, DatasetVersion
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import dataset_repo
from app.schemas.dataset import (
    DatasetCaseContent,
    DatasetCaseCreate,
    DatasetCaseUpdate,
    DatasetCreate,
)
from app.services.dataset import DatasetService, GeneratedCase

pytestmark = pytest.mark.anyio

_CSV = b"input,reference_answer\nImported one?,Yes\nImported two?,No\n"


async def _owner(db: AsyncSession) -> AuthContext:
    person = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", is_active=True)
    db.add(person)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=person.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=org.id,
            user_id=person.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


def _case(question: str) -> DatasetCaseCreate:
    return DatasetCaseCreate(input=question, reference_answer="An answer.")


async def _versions(db: AsyncSession, dataset_id: uuid.UUID) -> list[DatasetVersion]:
    return list(
        (
            await db.execute(
                select(DatasetVersion)
                .where(DatasetVersion.dataset_id == dataset_id)
                .order_by(DatasetVersion.number)
            )
        )
        .scalars()
        .all()
    )


async def _read(
    db: AsyncSession, ctx: AuthContext, version: DatasetVersion
) -> list[tuple[uuid.UUID, uuid.UUID, str]]:
    cases = await dataset_repo.list_cases(
        db, version.id, organization_id=ctx.organization_id, limit=None
    )
    assert len(cases) == version.case_count
    return [(case.id, case.case_id, case.input) for case in cases]


async def test_no_change_alters_what_an_earlier_version_holds(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    seen: dict[int, list[tuple[uuid.UUID, uuid.UUID, str]]] = {}

    async def change_then_reread() -> None:
        for version in await _versions(db, dataset.id):
            current = await _read(db, ctx, version)
            assert seen.setdefault(version.number, current) == current, version.number

    for question in ("First?", "Second?", "Third?"):
        await service.add_case(ctx, dataset.id, _case(question))
        await change_then_reread()
    await service.import_cases(ctx, dataset.id, content=_CSV, filename="more.csv", fmt="csv")
    await change_then_reread()
    locked = await service.lock_for_edit(ctx, dataset.id)
    await service.add_generated(
        ctx,
        locked,
        [GeneratedCase(content=DatasetCaseContent(input="Drafted?", reference_answer="Yes."))],
    )
    await change_then_reread()
    first, second = (await service.list_cases(ctx, dataset.id)).items[:2]
    await service.update_case(ctx, dataset.id, second.case_id, DatasetCaseUpdate(input="Second!"))
    await change_then_reread()
    await service.remove_case(ctx, dataset.id, first.case_id)
    await change_then_reread()
    await service.add_case(ctx, dataset.id, _case("Fourth?"))
    await change_then_reread()

    assert [question for *_, question in seen[8]] == [
        "Second!",
        "Third?",
        "Imported one?",
        "Imported two?",
        "Drafted?",
        "Fourth?",
    ]
    assert [question for *_, question in seen[5]][:2] == ["First?", "Second?"]
    # Edits and removals stored one revision each at most: nothing was copied.
    assert (
        await db.scalar(
            select(func.count(DatasetCase.id)).where(DatasetCase.dataset_id == dataset.id)
        )
        == 8
    )
    stats = (await dataset_repo.case_stats(db, [dataset.id], organization_id=ctx.organization_id))[
        dataset.id
    ]
    assert stats.with_reference == 6


async def test_an_older_version_pages_filters_and_places_as_it_did(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    for question in ("One?", "Two?", "Three?"):
        await service.add_case(ctx, dataset.id, _case(question))
    held = (await service.list_cases(ctx, dataset.id)).items
    await service.remove_case(ctx, dataset.id, held[2].case_id)
    await service.update_case(ctx, dataset.id, held[1].case_id, DatasetCaseUpdate(input="Too?"))
    v3, v5 = (await _versions(db, dataset.id))[2], (await _versions(db, dataset.id))[4]
    org = ctx.organization_id

    page = await dataset_repo.list_cases(db, v3.id, organization_id=org, skip=1, limit=1)
    assert [case.input for case in page] == ["Two?"]
    asked = await dataset_repo.list_cases(db, v3.id, organization_id=org, same_input="  two? ")
    assert [case.id for case in asked] == [held[1].id]
    assert await dataset_repo.list_cases(db, v5.id, organization_id=org, same_input="two?") == []
    found = await dataset_repo.find_case(db, v3.id, held[2].case_id, organization_id=org)
    assert found is not None and (found[0].id, found[1]) == (held[2].id, 2)
    assert await dataset_repo.find_case(db, v5.id, held[2].case_id, organization_id=org) is None
    assert await dataset_repo.last_position(db, v3.id, organization_id=org) == 2
    assert await dataset_repo.last_position(db, v5.id, organization_id=org) == 1
    # The edit kept its place: the reworded case is where the old one was.
    edited = await dataset_repo.find_case(db, v5.id, held[1].case_id, organization_id=org)
    assert edited is not None and edited[1] == 1 and edited[0].id != held[1].id


async def test_closing_a_revision_never_reaches_an_existing_version(db) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    await service.add_case(ctx, dataset.id, _case("One?"))
    await service.add_case(ctx, dataset.id, _case("Two?"))
    one, two = (await service.list_cases(ctx, dataset.id)).items
    org = ctx.organization_id

    # Not at or before the version that added it, and not again once closed.
    await dataset_repo.close_revisions(db, [two.id], organization_id=org, at=2)
    await dataset_repo.close_revisions(db, [one.id], organization_id=org, at=3)
    await dataset_repo.close_revisions(db, [one.id], organization_id=org, at=4)
    await dataset_repo.close_revisions(db, [one.id], organization_id=uuid.uuid4(), at=5)
    await dataset_repo.close_revisions(db, [], organization_id=org, at=5)
    db.expire_all()

    rows = {
        row.id: row.removed_in for row in (await db.execute(select(DatasetCase))).scalars().all()
    }
    assert rows == {one.id: 3, two.id: None}


async def test_two_changes_at_once_become_two_versions_that_do_not_overlap(db, engine) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="refunds"))
    await service.add_case(ctx, dataset.id, _case("One?"))
    await db.commit()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def add(question: str) -> None:
        async with session_factory() as session:
            await DatasetService(session).add_case(ctx, dataset.id, _case(question))
            await session.commit()

    await asyncio.gather(add("Two?"), add("Three?"))

    db.expire_all()
    versions = await _versions(db, dataset.id)
    assert [(v.number, v.case_count) for v in versions] == [(1, 1), (2, 2), (3, 3)]
    revisions = (
        (await db.execute(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id)))
        .scalars()
        .all()
    )
    assert sorted((r.added_in, r.position, r.removed_in) for r in revisions) == [
        (1, 0, None),
        (2, 1, None),
        (3, 2, None),
    ]


async def test_counts_taken_at_one_version_ignore_a_case_added_while_they_run(db) -> None:
    """Each of the three counting queries is its own statement and sees what
    committed before it, so all three are held to the versions read first: a case
    committed in between counts in none of them, whichever dataset it lands in."""
    ctx = await _owner(db)
    service = DatasetService(db)
    tagged = DatasetCaseCreate(input="One?", reference_answer="Yes.", tags=["refunds"])
    grown = await service.create(ctx, DatasetCreate(name="grown"))
    await service.add_case(ctx, grown.id, tagged)
    emptied = await service.create(ctx, DatasetCreate(name="emptied"))
    await service.add_case(ctx, emptied.id, _case("Gone?"))
    [gone] = (await service.list_cases(ctx, emptied.id)).items
    await service.remove_case(ctx, emptied.id, gone.case_id)
    pinned = {grown.id: 1, emptied.id: 2}

    # The write a concurrent request commits between the counts and the tags.
    await service.add_case(ctx, grown.id, tagged.model_copy(update={"input": "Two?"}))
    await service.add_case(ctx, emptied.id, tagged.model_copy(update={"input": "Back?"}))

    at_pin = await dataset_repo.case_stats_at(db, pinned, organization_id=ctx.organization_id)
    assert set(at_pin) == {grown.id}
    assert at_pin[grown.id].with_reference == 1
    assert [(tag.tag, tag.cases) for tag in at_pin[grown.id].top_tags] == [("refunds", 1)]
    assert sum(group.cases for group in at_pin[grown.id].tag_groups) == 1

    newest = await dataset_repo.case_stats(
        db, [grown.id, emptied.id], organization_id=ctx.organization_id
    )
    assert newest[grown.id].with_reference == 2
    assert [(tag.tag, tag.cases) for tag in newest[emptied.id].top_tags] == [("refunds", 1)]
    listed = {item.name: item for item in (await service.list_readable(ctx)).items}
    assert listed["grown"].stats.with_reference == 2
    never = await service.create(ctx, DatasetCreate(name="never"))
    assert await dataset_repo.case_stats(db, [never.id], organization_id=ctx.organization_id) == {}


async def test_a_revision_the_counts_did_not_see_is_skipped_by_the_tag_queries(
    db, monkeypatch
) -> None:
    ctx = await _owner(db)
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="racing"))
    donor = await service.create(ctx, DatasetCreate(name="donor"))
    await service.add_case(
        ctx, donor.id, DatasetCaseCreate(input="Late?", reference_answer="Yes.", tags=["late"])
    )
    execute = db.execute
    calls = 0

    async def move_a_revision_in_after_the_counts(*args, **kwargs):
        nonlocal calls
        result = await execute(*args, **kwargs)
        calls += 1
        if calls == 1:
            await execute(
                update(DatasetCase)
                .where(DatasetCase.dataset_id == donor.id)
                .values(dataset_id=dataset.id)
            )
        return result

    monkeypatch.setattr(db, "execute", move_a_revision_in_after_the_counts)
    stats = await dataset_repo.case_stats_at(
        db, {dataset.id: 1}, organization_id=ctx.organization_id
    )
    assert stats == {}
