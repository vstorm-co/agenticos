"""Tests for the resource grant repository - the table behind every share.

A repository's behaviour *is* the statement it builds, so these tests read the
statement back rather than counting calls. That matters most for the predicate:
a dropped ``organization_id`` filter is a cross-tenant read that no assertion
about "the repository was called" would ever notice, and a wrong level filter
hands out edit rights to people who were granted read.

What the schema guarantees on top of this - one grant per member per resource,
only the three defined levels - is asserted against a real database in
``tests/integration/test_schema_guarantees.py``.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.repositories import resource_grant_repo

pytestmark = pytest.mark.anyio


class _RecordingSession:
    """An ``AsyncSession`` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[ResourceGrant] = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: ResourceGrant) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        pass

    async def refresh(self, instance: ResourceGrant) -> None:
        pass


def _filters(session: _RecordingSession) -> dict[str, object]:
    """The values the last statement actually filters on."""
    return session.statements[-1].compile(dialect=postgresql.dialect()).params


def _sql(session: _RecordingSession) -> str:
    return str(session.statements[-1].compile(dialect=postgresql.dialect()))


def _scalar(value: object):
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _rows(values: list):
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=values))))


def _affected(count: int | None):
    return MagicMock(rowcount=count)


class TestGetLevel:
    async def test_a_stored_level_comes_back_as_the_enum(self):
        """Callers rank it through ``GRANT_ORDER``, which a bare string misses entirely."""
        session = _RecordingSession(_scalar(GrantLevel.EDIT.value))

        level = await resource_grant_repo.get_level(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert level is GrantLevel.EDIT

    async def test_a_member_who_was_never_granted_anything_has_no_level(self):
        """``None`` is what makes the access check fall through to the role scope."""
        session = _RecordingSession(_scalar(None))

        level = await resource_grant_repo.get_level(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert level is None

    async def test_the_lookup_names_the_organization_member_and_resource(self):
        """Any one of these four missing widens the query into somebody else's grant."""
        session = _RecordingSession(_scalar(None))
        organization_id, subject_user_id, resource_id = (uuid.uuid4() for _ in range(3))

        await resource_grant_repo.get_level(
            session,
            organization_id=organization_id,
            subject_user_id=subject_user_id,
            resource_type="collection",
            resource_id=resource_id,
        )

        assert set(_filters(session).values()) == {
            organization_id,
            subject_user_id,
            "collection",
            resource_id,
        }


class TestListSharedIds:
    @pytest.mark.parametrize(
        ("minimum_level", "accepted"),
        [
            (GrantLevel.READ, {"read", "use", "edit"}),
            (GrantLevel.USE, {"use", "edit"}),
            (GrantLevel.EDIT, {"edit"}),
        ],
    )
    async def test_a_minimum_level_accepts_every_level_above_it(self, minimum_level, accepted):
        """Levels are ranked, not matched.

        Someone granted *edit* can obviously also *use* the resource; requiring
        an exact match would hide their own agents from a listing that asked for
        everything they may run.
        """
        session = _RecordingSession(_rows([]))

        await resource_grant_repo.list_shared_ids(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            minimum_level=minimum_level,
        )

        assert set(_filters(session)["level_1"]) == accepted

    async def test_read_is_the_default_because_listing_only_needs_visibility(self):
        session = _RecordingSession(_rows([]))

        await resource_grant_repo.list_shared_ids(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
        )

        assert set(_filters(session)["level_1"]) == {"read", "use", "edit"}

    async def test_only_the_ids_of_one_resource_type_are_returned(self):
        """These widen a listing query; an id of the wrong kind would widen it wrongly."""
        session = _RecordingSession(_rows([]))
        subject_user_id = uuid.uuid4()

        await resource_grant_repo.list_shared_ids(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=subject_user_id,
            resource_type="skill",
        )

        filters = _filters(session)
        assert filters["resource_type_1"] == "skill"
        assert filters["subject_user_id_1"] == subject_user_id

    async def test_the_shared_ids_come_back_as_a_list(self):
        shared = [uuid.uuid4(), uuid.uuid4()]
        session = _RecordingSession(_rows(shared))

        found = await resource_grant_repo.list_shared_ids(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
        )

        assert found == shared


class TestListForResource:
    async def test_the_sharing_panel_reads_grants_oldest_first(self):
        """A panel that reorders itself between refreshes is one people misread."""
        session = _RecordingSession(_rows([]))

        await resource_grant_repo.list_for_resource(
            session,
            organization_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert "ORDER BY resource_grants.created_at ASC" in _sql(session)

    async def test_every_member_the_resource_was_shared_with_is_listed(self):
        """No subject filter: this answers "who reaches this", not "do I"."""
        grants = [MagicMock(), MagicMock()]
        session = _RecordingSession(_rows(grants))
        organization_id, resource_id = uuid.uuid4(), uuid.uuid4()

        found = await resource_grant_repo.list_for_resource(
            session,
            organization_id=organization_id,
            resource_type="agent",
            resource_id=resource_id,
        )

        assert found == grants
        assert set(_filters(session).values()) == {organization_id, "agent", resource_id}


class TestUpsert:
    async def test_sharing_with_someone_new_writes_a_grant(self):
        session = _RecordingSession(_scalar(None))
        organization_id, subject_user_id, resource_id, actor = (uuid.uuid4() for _ in range(4))

        grant = await resource_grant_repo.upsert(
            session,
            organization_id=organization_id,
            subject_user_id=subject_user_id,
            resource_type="agent",
            resource_id=resource_id,
            level=GrantLevel.USE,
            created_by_user_id=actor,
        )

        assert session.added == [grant]
        assert (grant.organization_id, grant.subject_user_id) == (organization_id, subject_user_id)
        assert (grant.resource_type, grant.resource_id) == ("agent", resource_id)
        assert grant.level == GrantLevel.USE.value
        assert grant.created_by_user_id == actor

    async def test_sharing_again_moves_the_existing_grant_instead_of_adding_a_second(self):
        """Two rows for one member would make "what level do they have" unanswerable.

        The database refuses the second row anyway; doing it here is what turns
        re-sharing at a different level into an ordinary edit rather than an
        integrity error.
        """
        existing = ResourceGrant(level=GrantLevel.READ.value)
        session = _RecordingSession(_scalar(existing))

        grant = await resource_grant_repo.upsert(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
            level=GrantLevel.EDIT,
        )

        assert grant is existing
        assert existing.level == GrantLevel.EDIT.value
        assert session.added == []


class TestRevoke:
    async def test_removing_a_share_that_existed_reports_that_it_did(self):
        session = _RecordingSession(_affected(1))

        removed = await resource_grant_repo.revoke(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert removed is True

    async def test_removing_a_share_that_was_never_there_reports_nothing_removed(self):
        """The sharing service turns this into a 404, so the two cases must differ."""
        session = _RecordingSession(_affected(0))

        removed = await resource_grant_repo.revoke(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert removed is False

    async def test_only_the_named_member_loses_their_share(self):
        """Unsharing with one person must not unshare with the rest of the team."""
        session = _RecordingSession(_affected(1))
        subject_user_id = uuid.uuid4()

        await resource_grant_repo.revoke(
            session,
            organization_id=uuid.uuid4(),
            subject_user_id=subject_user_id,
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert _filters(session)["subject_user_id_1"] == subject_user_id


class TestDeleteForResource:
    async def test_deleting_a_resource_drops_the_grants_of_every_member(self):
        """No foreign key points at the resource, so nothing cascades on its behalf.

        The subject is deliberately absent from the predicate: this runs when the
        agent or collection itself is gone, and every share of it goes with it.
        """
        session = _RecordingSession(_affected(3))
        organization_id, resource_id = uuid.uuid4(), uuid.uuid4()

        removed = await resource_grant_repo.delete_for_resource(
            session,
            organization_id=organization_id,
            resource_type="agent",
            resource_id=resource_id,
        )

        assert removed == 3
        assert set(_filters(session).values()) == {organization_id, "agent", resource_id}

    async def test_deleting_a_resource_nobody_shared_removes_nothing(self):
        session = _RecordingSession(_affected(0))

        removed = await resource_grant_repo.delete_for_resource(
            session,
            organization_id=uuid.uuid4(),
            resource_type="agent",
            resource_id=uuid.uuid4(),
        )

        assert removed == 0
