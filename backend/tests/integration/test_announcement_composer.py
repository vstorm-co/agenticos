"""The app-admin announcement composer, against a real database (#1598,
Decision 5).

Decision 5's own hard parts are all here: a member reachable through two
selected organizations gets exactly one notification, `"all organizations"`
resolves to whoever currently belongs to something rather than a frozen
list, a role narrows the audience without narrowing which organizations were
addressed, and the send is refused - unwritten - rather than recorded
against nobody when the resolved audience is empty.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.exceptions import BadRequestError
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.announcement import AnnouncementService

pytestmark = pytest.mark.anyio


async def _user(db, **overrides) -> User:
    fields = {
        "id": uuid.uuid4(),
        "email": f"{uuid.uuid4().hex}@example.com",
        "hashed_password": "x",
        "is_active": True,
    }
    fields.update(overrides)
    user = User(**fields)
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str, created_by: User | None = None) -> Organization:
    creator = created_by or await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=creator.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _member(db, org: Organization, user: User, *, role: str = "member") -> None:
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()


class TestAllOrganizations:
    async def test_reaches_every_current_member_across_organizations(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        globex = await _org(db, name="Globex")
        alice = await _user(db)
        bob = await _user(db)
        await _member(db, acme, alice)
        await _member(db, globex, bob)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Maintenance tonight", organizations="all", role=None
        )

        assert result.recipient_count == 2

    async def test_a_role_narrows_within_all_organizations(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        owner = await _user(db)
        member = await _user(db)
        await _member(db, acme, owner, role="owner")
        await _member(db, acme, member, role="member")

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Owners only", organizations="all", role="owner"
        )

        assert result.recipient_count == 1


class TestExplicitOrganizations:
    async def test_reaches_only_the_selected_organizations(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        globex = await _org(db, name="Globex")
        in_scope = await _user(db)
        out_of_scope = await _user(db)
        await _member(db, acme, in_scope)
        await _member(db, globex, out_of_scope)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Acme only", organizations=[acme.id], role=None
        )

        assert result.recipient_count == 1
        [notification] = (
            (await db.execute(select(Notification).where(Notification.announcement_id.isnot(None))))
            .scalars()
            .all()
        )
        assert notification.recipient_user_id == in_scope.id

    async def test_a_member_of_two_selected_organizations_gets_one_notification(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        globex = await _org(db, name="Globex")
        both = await _user(db)
        await _member(db, acme, both)
        await _member(db, globex, both)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id,
            body="Belongs to both",
            organizations=[acme.id, globex.id],
            role=None,
        )

        assert result.recipient_count == 1
        rows = (
            (
                await db.execute(
                    select(Notification).where(Notification.recipient_user_id == both.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_an_empty_resolved_audience_is_refused_and_writes_nothing(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        member = await _user(db)
        await _member(db, acme, member, role="member")

        with pytest.raises(BadRequestError):
            await AnnouncementService(db).send(
                actor_user_id=sender.id,
                body="Owners only, but there are none",
                organizations=[acme.id],
                role="owner",
            )

        announcements = (await db.execute(select(AppAdminAuditLog))).scalars().all()
        assert announcements == []


class TestWhatGetsWritten:
    async def test_the_notification_carries_no_organization_and_the_announcement_id(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        member = await _user(db)
        await _member(db, acme, member)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Hello", organizations=[acme.id], role=None
        )

        notification = await db.scalar(
            select(Notification).where(Notification.recipient_user_id == member.id)
        )
        assert notification is not None
        assert notification.event_type == NotificationEventType.ANNOUNCEMENT.value
        assert notification.organization_id is None
        assert notification.announcement_id == result.announcement.id
        assert notification.occurrence_id == str(result.announcement.id)
        assert notification.summary == "Hello"

    async def test_the_audience_spec_stores_organization_ids_as_strings(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        member = await _user(db)
        await _member(db, acme, member)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Hello", organizations=[acme.id], role=None
        )

        assert result.announcement.audience_spec == {
            "organizations": [str(acme.id)],
            "role": None,
        }

    async def test_the_audience_description_names_the_selected_organizations(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        globex = await _org(db, name="Globex")
        member = await _user(db)
        await _member(db, acme, member)
        await _member(db, globex, member)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id,
            body="Hello",
            organizations=[acme.id, globex.id],
            role="member",
        )

        assert result.announcement.audience_description == "Acme, Globex - members"

    async def test_all_organizations_description_names_no_organization(self, db):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        member = await _user(db)
        await _member(db, acme, member)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Hello", organizations="all", role=None
        )

        assert result.announcement.audience_description == "All organizations"

    async def test_the_audit_entry_carries_the_count_and_description_not_the_recipient_list(
        self, db
    ):
        sender = await _user(db, is_app_admin=True)
        acme = await _org(db, name="Acme")
        member = await _user(db)
        await _member(db, acme, member)

        result = await AnnouncementService(db).send(
            actor_user_id=sender.id, body="Hello", organizations=[acme.id], role=None
        )

        entry = await db.scalar(
            select(AppAdminAuditLog).where(AppAdminAuditLog.action == "announcement.sent")
        )
        assert entry is not None
        assert entry.actor_user_id == sender.id
        assert entry.target_id == str(result.announcement.id)
        assert entry.details == {
            "audience_description": "Acme",
            "recipient_count": 1,
        }
