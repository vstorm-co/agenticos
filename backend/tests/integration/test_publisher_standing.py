"""What role a public surface's turn takes, against real rows.

`publisher_context` is the one answer to "who does an anonymous turn run as", and
what it reads has to be a *join*: a membership row survives its user being
deactivated, so a role read off the membership alone is the authority of an account
that is refused everywhere a person signs in. That is a two-table fact, so a mocked
session cannot show it - `member_repo.get` and `member_repo.get_active` return the
same stand-in to a `MagicMock` whatever the SQL says.

Three rows, three answers, and the middle one is the defect: still a member, still
recorded, and no longer able to sign in.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.permissions import OrgRoleName
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.access import publisher_context

pytestmark = pytest.mark.anyio


async def _user(db, *, is_active: bool) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db) -> Organization:
    founder = await _user(db, is_active=True)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization


async def _member(db, organization: Organization, user: User, role: str) -> None:
    db.add(
        OrganizationMember(
            id=uuid.uuid4(), organization_id=organization.id, user_id=user.id, role=role
        )
    )
    await db.flush()


class TestWhichRoleAnAnonymousTurnBorrows:
    async def test_a_publisher_who_can_still_sign_in_lends_their_role(self, db) -> None:
        organization = await _org(db)
        publisher = await _user(db, is_active=True)
        await _member(db, organization, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.OWNER.value
        # `user_id` is the publisher, not whoever is chatting, so a personal-memory write
        # is refused rather than attributing a stranger's note to the owner (#788).
        assert ctx.subject_is_publisher_fallback is True

    async def test_a_deactivated_publisher_lends_nothing(self, db) -> None:
        """The row that made this worth an integration test. Deactivating a user
        leaves their membership exactly where it was, so their widget, hosted page
        and channel binding kept answering at Owner while the account itself was
        refused on every path a person signs in through.
        """
        organization = await _org(db)
        publisher = await _user(db, is_active=False)
        await _member(db, organization, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.VIEWER.value
        assert ctx.user_id == publisher.id, "still the honest record of who published"

    async def test_a_publisher_who_left_lends_nothing(self, db) -> None:
        organization = await _org(db)
        publisher = await _user(db, is_active=True)

        ctx = await publisher_context(
            db, organization_id=organization.id, publisher_user_id=publisher.id
        )

        assert ctx.role == OrgRoleName.VIEWER.value

    async def test_a_membership_in_another_organization_lends_nothing_here(self, db) -> None:
        """The join must not widen what the tenant check already decided."""
        theirs, ours = await _org(db), await _org(db)
        publisher = await _user(db, is_active=True)
        await _member(db, theirs, publisher, OrgRoleName.OWNER.value)

        ctx = await publisher_context(db, organization_id=ours.id, publisher_user_id=publisher.id)

        assert ctx.role == OrgRoleName.VIEWER.value


async def test_a_publisher_context_is_always_flagged_a_fallback() -> None:
    """The flag is unconditional: with no publisher recorded the DB is never
    touched, and the context is still a fallback whose personal-memory writes must
    be refused."""
    ctx = await publisher_context(MagicMock(), organization_id=uuid.uuid4(), publisher_user_id=None)
    assert ctx.subject_is_publisher_fallback is True
    assert ctx.role == OrgRoleName.VIEWER.value


def test_only_publisher_context_sets_the_fallback_flag() -> None:
    """The N1 guarantee that per-user memory never leaks into the owner's store
    rests on `subject_is_publisher_fallback` being set `True` only where the id in
    hand is an authority rather than a person at the keyboard. A stand-in
    constructor that forgot it would run a visitor's turn as the owner without the
    flag, and per-user memory would attribute the visitor's notes to the owner.
    This pins the assignment sites by grep - the same discipline that keeps
    `AuthContext.anonymous` the sole subject-less constructor - so a new one has to
    be argued for in a diff rather than added quietly.

    Two sites are legitimate: `services/access.py` mints the publisher-standing
    context for a hosted/widget run, and `services/agent_trigger.py` mints the
    fired-run context whose `user_id` is the trigger *creator* (the authority an
    unattended run executes under), which must not become a memory end-user (#788).
    """
    app_root = Path(__file__).resolve().parents[2] / "app"
    setters = sorted(
        path.relative_to(app_root).as_posix()
        for path in app_root.rglob("*.py")
        if "subject_is_publisher_fallback=True" in path.read_text(encoding="utf-8")
    )
    assert setters == ["services/access.py", "services/agent_trigger.py"], setters
