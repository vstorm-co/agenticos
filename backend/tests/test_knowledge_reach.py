"""Whether an agent reaches people its knowledge does not (#2072)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.permissions import AuthContext
from app.db.models.resource_grant import ResourceGrant, Visibility
from app.db.models.skill import Skill
from app.services.access import SKILL
from app.services.knowledge_reach import KnowledgeReachService, _Reach

ALICE, BOB = uuid.uuid4(), uuid.uuid4()
FINANCE = uuid.uuid4()


def _shared(*, groups: tuple[uuid.UUID, ...] = (), people: tuple[uuid.UUID, ...] = ()) -> _Reach:
    return _Reach(everyone=False, group_ids=frozenset(groups), user_ids=frozenset(people))


EVERYONE = _Reach(everyone=True, group_ids=frozenset(), user_ids=frozenset())


def test_people_are_compared_by_who_they_are():
    """Codex on #2062: an agent shared with Alice over a source shared with Bob
    answered Alice from a source she cannot open, and no warning said so."""
    assert _shared(people=(ALICE,)).wider_than(_shared(people=(BOB,)))
    assert not _shared(people=(ALICE,)).wider_than(_shared(people=(ALICE, BOB)))


def test_a_group_the_source_lacks_is_wider():
    assert _shared(groups=(FINANCE,)).wider_than(_shared())
    assert not _shared(groups=(FINANCE,)).wider_than(_shared(groups=(FINANCE,)))


def test_everyone_on_either_side_decides():
    assert EVERYONE.wider_than(_shared(people=(ALICE,)))
    assert not _shared(people=(ALICE,)).wider_than(EVERYONE)


@pytest.mark.anyio
async def test_audience_reads_are_batched_and_keep_groups_and_people_separate() -> None:
    organization = uuid.uuid4()
    ctx = AuthContext(user_id=ALICE, organization_id=organization, role="owner")
    rows = [
        Skill(
            id=uuid.uuid4(),
            organization_id=organization,
            owner_user_id=ALICE,
            visibility=Visibility.PRIVATE.value,
        )
        for _ in range(40)
    ]
    public = Skill(
        id=uuid.uuid4(),
        organization_id=organization,
        owner_user_id=ALICE,
        visibility=Visibility.ORG.value,
    )
    grants = [
        ResourceGrant(resource_id=rows[0].id, subject_group_id=FINANCE),
        ResourceGrant(resource_id=rows[0].id, subject_user_id=BOB),
    ]
    with patch(
        "app.services.knowledge_reach.resource_grant_repo.list_for_resources",
        AsyncMock(return_value=grants),
    ) as listing:
        result = await KnowledgeReachService(MagicMock())._reaches(ctx, [*rows, public], SKILL)
    listing.assert_awaited_once()
    assert set(listing.await_args.kwargs["resource_ids"]) == {row.id for row in rows}
    assert listing.await_args.kwargs["organization_id"] == organization
    assert result[rows[0].id] == _shared(groups=(FINANCE,), people=(BOB,))
    assert result[rows[1].id] == _shared()
    assert result[public.id] == EVERYONE


@pytest.mark.anyio
@pytest.mark.parametrize("resource_ids", [[], [ALICE, BOB]])
async def test_batch_audience_repository_does_not_query_an_empty_set(
    resource_ids: list[uuid.UUID],
) -> None:
    from app.repositories import resource_grant_repo

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.execute.return_value.scalars.return_value.all.return_value = []
    assert (
        await resource_grant_repo.list_for_resources(
            db, organization_id=uuid.uuid4(), resource_type="skill", resource_ids=resource_ids
        )
        == []
    )
    assert db.execute.await_count == (1 if resource_ids else 0)
