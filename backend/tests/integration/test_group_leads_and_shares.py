"""A department runs itself: its lead, its page's "add to this group", and its inbox (#2072)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.group import Group, GroupMember
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.user import User
from app.schemas.group import GroupShareItem
from app.schemas.skill import SkillCreate
from app.services.group import GroupService
from app.services.group_sharing import GroupSharingService
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _member(db: AsyncSession, organization: Organization, role: str) -> AuthContext:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization.id, role=role)


async def _setup(db: AsyncSession) -> tuple[Organization, AuthContext]:
    owner = await _person(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"))
    await db.flush()
    return organization, AuthContext(
        user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER
    )


async def _department(db: AsyncSession, organization: Organization, *people: AuthContext) -> Group:
    group = Group(organization_id=organization.id, name=f"Dept {uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for person in people:
        assert person.user_id is not None
        db.add(GroupMember(group_id=group.id, user_id=person.user_id))
    await db.flush()
    return group


async def _skill(db: AsyncSession, ctx: AuthContext, name: str, **fields: object):
    data = SkillCreate(name=name, description="x", **fields)
    return await SkillService(db).create(
        ctx,
        name=data.name,
        description=data.description,
        content=data.content,
        visibility=data.visibility,
        group_ids=data.group_ids,
        user_ids=data.user_ids,
    )


async def _shared_notices(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    rows = await db.scalars(
        select(Notification.summary).where(
            Notification.recipient_user_id == user_id,
            Notification.event_type == NotificationEventType.RESOURCE_SHARED.value,
        )
    )
    return list(rows)


class TestTheLead:
    async def test_a_lead_runs_who_is_in_their_group_and_nobody_else_s(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _setup(db)
        lead = await _member(db, organization, "member")
        newcomer = await _member(db, organization, "member")
        finance = await _department(db, organization, lead)
        sales = await _department(db, organization)
        assert owner.user_id and lead.user_id and newcomer.user_id
        service = GroupService(db)

        member, _email, _name = await service.set_lead(
            organization.id, finance.id, lead.user_id, owner.user_id, is_lead=True
        )
        assert member.is_lead

        await service.add_member(organization.id, finance.id, newcomer.user_id, lead.user_id)
        await service.remove_member(organization.id, finance.id, newcomer.user_id, lead.user_id)
        with pytest.raises(AuthorizationError):
            await service.add_member(organization.id, sales.id, newcomer.user_id, lead.user_id)

    async def test_only_an_administrator_names_a_lead(self, db: AsyncSession) -> None:
        organization, owner = await _setup(db)
        member = await _member(db, organization, "member")
        finance = await _department(db, organization, member)
        assert member.user_id and owner.user_id

        with pytest.raises(AuthorizationError):
            await GroupService(db).set_lead(
                organization.id, finance.id, member.user_id, member.user_id, is_lead=True
            )
        with pytest.raises(NotFoundError):
            await GroupService(db).set_lead(
                organization.id, finance.id, owner.user_id, owner.user_id, is_lead=True
            )


class TestTheInbox:
    async def test_a_group_s_members_are_told_and_whoever_shared_it_is_not(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _setup(db)
        accountant = await _member(db, organization, "member")
        finance = await _department(db, organization, accountant, owner)
        assert accountant.user_id and owner.user_id

        await _skill(db, owner, "month-end-close", group_ids=[finance.id])

        assert await _shared_notices(db, accountant.user_id) == [
            f"'month-end-close' was shared with {finance.name}."
        ]
        assert await _shared_notices(db, owner.user_id) == []


class TestAddToThisGroup:
    async def test_it_offers_what_the_caller_may_edit_and_the_group_lacks(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _setup(db)
        builder = await _member(db, organization, "member")
        finance = await _department(db, organization)
        await _skill(db, builder, "my-notes", visibility=Visibility.PRIVATE)
        await _skill(db, owner, "house-style")
        await _skill(db, builder, "already", group_ids=[finance.id])

        offered = await GroupSharingService(db).shareable(builder, finance.id)

        assert [(item.kind, item.name) for item in offered] == [("skill", "my-notes")]

    async def test_it_shares_several_at_once_and_refuses_what_the_caller_cannot_edit(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _setup(db)
        builder = await _member(db, organization, "member")
        finance = await _department(db, organization)
        mine = await _skill(db, builder, "my-notes", visibility=Visibility.PRIVATE)
        theirs = await _skill(db, owner, "house-style")
        service = GroupSharingService(db)

        await service.share(
            builder, finance.id, [GroupShareItem(kind="skill", id=mine.id)], level=GrantLevel.USE
        )
        listed = await GroupService(db).resources(owner, finance.id)
        assert [(item.kind, item.name) for item in listed] == [("skill", "my-notes")]

        with pytest.raises(AuthorizationError):
            await service.share(
                builder,
                finance.id,
                [GroupShareItem(kind="skill", id=theirs.id)],
                level=GrantLevel.USE,
            )
        with pytest.raises(NotFoundError):
            await service.share(
                builder,
                finance.id,
                [GroupShareItem(kind="agent", id=uuid.uuid4())],
                level=GrantLevel.USE,
            )
        with pytest.raises(NotFoundError):
            await service.shareable(builder, uuid.uuid4())


async def test_a_card_names_the_departments_a_resource_belongs_to(db: AsyncSession) -> None:
    from app.services.access import SKILL
    from app.services.resource_usage import groups_sharing

    organization, owner = await _setup(db)
    finance = await _department(db, organization)
    sales = await _department(db, organization)
    both = await _skill(db, owner, "pricing", group_ids=[sales.id, finance.id])
    open_to_all = await _skill(db, owner, "house-style")

    shared = await groups_sharing(
        db, owner, resource_type=SKILL, resource_ids=[both.id, open_to_all.id]
    )
    listing = await SkillService(db).list_readable(owner)

    assert shared == {both.id: sorted([finance.name, sales.name]), open_to_all.id: []}
    by_name = {item.name: item.shared_groups for item in listing.items}
    assert by_name["pricing"] == sorted([finance.name, sales.name])
