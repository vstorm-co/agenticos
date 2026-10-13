"""An ML service call belongs to the organization that made it, and to no other.

The unit suite mocks the repository, so it can only prove that the service passes
an organization id down. What a second tenant actually sees when it asks for the
row by id is a question for the database, and it is the one FA-069's acceptance
asks about: a service another Urban Stack component calls with a key must not let
one caller read another's usage.

So this writes real rows for two organizations and reads them back through the
service the routes use.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import ml_service_call_repo
from app.services.ml import MLService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _org(db, *, name: str) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


def _ctx(organization: Organization, member: User) -> AuthContext:
    return AuthContext(user_id=member.id, organization_id=organization.id, role=OrgRoleName.OWNER)


async def _call(db, organization: Organization, member: User, *, service: str = "ocr"):
    return await ml_service_call_repo.record(
        db,
        organization_id=organization.id,
        requested_by_user_id=member.id,
        service=service,
        status="succeeded",
        input_bytes=2048,
        units=4,
        unit="pages",
        duration_ms=1200,
    )


class TestOneTenantsCallsAreInvisibleToAnother:
    async def test_the_organization_that_made_the_call_reads_it_back(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        row = await _call(db, acme, founder)

        found = await MLService(db).call_record(_ctx(acme, founder), row.id)

        assert found.id == row.id
        assert found.units == 4

    async def test_another_organization_asking_by_id_is_told_it_does_not_exist(self, db) -> None:
        """Not found rather than forbidden, so ids stay unprobeable."""
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        row = await _call(db, acme, founder)

        with pytest.raises(NotFoundError):
            await MLService(db).call_record(_ctx(globex, other), row.id)

    async def test_the_listing_carries_only_the_callers_own_rows(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        mine = await _call(db, acme, founder)
        await _call(db, globex, other)

        rows, total = await MLService(db).call_records(
            _ctx(acme, founder), service=None, skip=0, limit=50
        )

        assert [row.id for row in rows] == [mine.id]
        assert total == 1

    async def test_narrowing_to_a_service_still_answers_inside_the_organization(self, db) -> None:
        acme, founder = await _org(db, name="Acme")
        globex, other = await _org(db, name="Globex")
        await _call(db, acme, founder, service="ocr")
        await _call(db, acme, founder, service="pii_detection")
        await _call(db, globex, other, service="ocr")

        rows, total = await MLService(db).call_records(
            _ctx(acme, founder), service="ocr", skip=0, limit=50
        )

        assert total == 1
        assert rows[0].organization_id == acme.id


class TestTheRowKeepsNoneOfWhatWasSubmitted:
    async def test_the_columns_are_the_shape_of_the_call_and_nothing_else(self, db) -> None:
        """A column added here that could hold content fails this test, on purpose."""
        acme, founder = await _org(db, name="Acme")
        row = await _call(db, acme, founder)

        assert set(row.__table__.columns.keys()) == {
            "id",
            "organization_id",
            "requested_by_user_id",
            "service",
            "status",
            "failure_stage",
            "failure_reason",
            "input_bytes",
            "units",
            "unit",
            "duration_ms",
            "created_at",
            "updated_at",
        }
