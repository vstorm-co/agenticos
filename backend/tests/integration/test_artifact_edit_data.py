"""The `edit_data` grant level, and a run asking to share a page, on real rows (#1974).

The consent suite's world: a page that belongs to Olga, and the people around it. An
`edit_data` grant is the owner's standing consent to an editor's republishes; these prove
what only a database can: the grant guard (a CHECK, and who may give the level), the
republish by its holder being consented under the owner's membership, the level dropping
when the owner changes or leaves, and `share_artifact`'s request being filed, merged and
never applied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.artifact import Artifact
from app.db.models.artifact_share_request import ShareRequestKind
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.group import Group, GroupMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo, resource_grant_repo
from app.schemas.artifact import ArtifactOwnerUpdate
from app.services import artifact as artifacts
from app.services.access import AGENT, ARTIFACT
from app.services.artifact_consent import EDIT_DATA_GROUP_WORDING, EDIT_DATA_PERSON_WORDING
from app.services.file_storage import LocalFileStorage
from app.services.member import MemberService
from app.services.sharing import SharingService
from tests.integration.test_artifact_consent import (
    WIDER,
    _actions,
    _World,
    _world,
    storage,
)
from tests.integration.test_artifact_requests import _pending

pytestmark = pytest.mark.anyio

__all__ = ["storage"]


async def _page(world: _World) -> Artifact:
    assert world.page_id is not None
    page = await artifact_repo.get(world.db, world.page_id, organization_id=world.org.id)
    assert page is not None
    return page


async def _consented(world: _World) -> None:
    """Olga's page, published and confirmed, so granting more people access is allowed."""
    await world.publish("<p>v1</p>")
    await world.confirm(world.olga, 1)


async def _grant(
    world: _World, subject: AuthContext, level: GrantLevel, *, confirmed: str | None = None
) -> None:
    result = await SharingService(world.db).share(
        world.olga,
        await _page(world),
        resource_type=ARTIFACT,
        subject_user_id=subject.user_id,  # type: ignore[arg-type]
        level=level,
        confirmed=confirmed,
    )
    assert isinstance(result, ResourceGrant)


async def _level(world: _World, subject: AuthContext) -> str | None:
    assert subject.user_id is not None and world.page_id is not None
    level = await resource_grant_repo.get_level(
        world.db,
        organization_id=world.org.id,
        subject_user_id=subject.user_id,
        resource_type=ARTIFACT.key,
        resource_id=world.page_id,
    )
    return level.value if level is not None else None


async def _group_of(world: _World, *members: AuthContext, name: str = "Sales") -> Group:
    group = Group(organization_id=world.org.id, name=name)
    world.db.add(group)
    await world.db.flush()
    for member in members:
        world.db.add(GroupMember(group_id=group.id, user_id=member.user_id))
    await world.db.flush()
    return group


class TestGrantingTheLevel:
    async def test_the_owner_gives_it_with_the_text_confirmed_and_the_audit_keeps_the_text(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        assert bea.user_id is not None

        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        assert await _level(world, bea) == "edit_data"
        beas_email = (await db.get(User, bea.user_id)).email  # type: ignore[union-attr]
        [(_, details)] = [
            entry
            for entry in await _actions(db, world.page_id)  # type: ignore[arg-type]
            if entry[0] == "artifact.edit_data_granted"
        ]
        assert details["subject_user_id"] == str(bea.user_id)
        assert details["wording"] == EDIT_DATA_PERSON_WORDING
        assert details["wording_text"].startswith(f"{beas_email} can change what data")
        assert "API runs" in details["wording_text"]

    async def test_a_group_gets_its_own_wording(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        group = await _group_of(world, await world.member())

        await SharingService(db).share_with_group(
            world.olga,
            await _page(world),
            resource_type=ARTIFACT,
            group_id=group.id,
            level=GrantLevel.EDIT_DATA,
            confirmed=EDIT_DATA_GROUP_WORDING,
        )

        [(_, details)] = [
            entry
            for entry in await _actions(db, world.page_id)  # type: ignore[arg-type]
            if entry[0] == "artifact.edit_data_granted"
        ]
        assert details["subject_group_id"] == str(group.id)
        assert details["wording_text"].startswith("Everyone in Sales, now and later,")

    @pytest.mark.parametrize("confirmed", [None, "edit_data.v0", EDIT_DATA_GROUP_WORDING])
    async def test_without_the_text_for_this_subject_nothing_is_given(
        self, db: AsyncSession, storage: LocalFileStorage, confirmed: str | None
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)

        with pytest.raises(BadRequestError) as refused:
            await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=confirmed)

        assert "confirmed" in str(refused.value.details)
        assert await _level(world, bea) == "edit"

    @pytest.mark.security
    async def test_an_editor_cannot_give_it_and_a_grant_to_edit_is_no_authority(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        cal = await world.member()

        with pytest.raises(AuthorizationError):
            await SharingService(db).share(
                bea,
                await _page(world),
                resource_type=ARTIFACT,
                subject_user_id=cal.user_id,  # type: ignore[arg-type]
                level=GrantLevel.EDIT_DATA,
                confirmed=EDIT_DATA_PERSON_WORDING,
            )
        assert await _level(world, cal) is None

    async def test_an_admin_gives_it_as_themselves_and_not_while_impersonated(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        admin = await world.member(role="admin")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        sharing = SharingService(db)
        page = await _page(world)

        set_impersonator(uuid.uuid4())
        try:
            with pytest.raises(AuthorizationError):
                await sharing.share(
                    admin,
                    page,
                    resource_type=ARTIFACT,
                    subject_user_id=bea.user_id,  # type: ignore[arg-type]
                    level=GrantLevel.EDIT_DATA,
                    confirmed=EDIT_DATA_PERSON_WORDING,
                )
        finally:
            set_impersonator(None)
        await sharing.share(
            admin,
            page,
            resource_type=ARTIFACT,
            subject_user_id=bea.user_id,  # type: ignore[arg-type]
            level=GrantLevel.EDIT_DATA,
            confirmed=EDIT_DATA_PERSON_WORDING,
        )

        assert await _level(world, bea) == "edit_data"

    async def test_any_editor_lowers_or_revokes_it_and_resaving_it_needs_no_text(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        cal = await world.member(page=GrantLevel.EDIT)
        dee = await world.member(page=GrantLevel.EDIT)
        for subject in (cal, dee):
            await _grant(world, subject, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)
        sharing = SharingService(db)
        page = await _page(world)

        await sharing.share(
            bea,
            page,
            resource_type=ARTIFACT,
            subject_user_id=cal.user_id,  # type: ignore[arg-type]
            level=GrantLevel.EDIT_DATA,
        )
        assert await _level(world, cal) == "edit_data"
        await sharing.share(
            bea,
            page,
            resource_type=ARTIFACT,
            subject_user_id=cal.user_id,  # type: ignore[arg-type]
            level=GrantLevel.EDIT,
        )
        await sharing.revoke(
            bea,
            page,
            resource_type=ARTIFACT,
            subject_user_id=dee.user_id,  # type: ignore[arg-type]
        )

        assert (await _level(world, cal), await _level(world, dee)) == ("edit", None)

    async def test_it_is_a_pages_level_only(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        admin = await world.member(role="admin")
        bea = await world.member()

        with pytest.raises(BadRequestError):
            await SharingService(db).share(
                admin,
                world.agent,
                resource_type=AGENT,
                subject_user_id=bea.user_id,  # type: ignore[arg-type]
                level=GrantLevel.EDIT_DATA,
            )
        group = await _group_of(world)
        with pytest.raises(BadRequestError):
            await SharingService(db).share_with_group(
                admin,
                world.agent,
                resource_type=AGENT,
                group_id=group.id,
                level=GrantLevel.EDIT_DATA,
            )

    async def test_the_database_refuses_it_on_anything_but_a_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await world.member()
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(
                    ResourceGrant(
                        organization_id=world.org.id,
                        subject_user_id=bea.user_id,
                        resource_type="agent",
                        resource_id=world.agent.id,
                        level="edit_data",
                    )
                )
                await db.flush()

    async def test_it_counts_as_an_edit_everywhere_a_level_is_ranked(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(reads_table=True)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        detail = await world.service.read(bea, world.page_id)  # type: ignore[arg-type]

        assert detail.owner_user_id == world.olga.user_id
        assert (await world.service._can_edit(bea, await _page(world))) is True


class TestRepublishingWithIt:
    async def test_the_holder_s_republish_is_consented_under_the_owner_via_their_grant(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        version = await world.version(2)
        assert (version.consent_state, version.consent_automatic) == ("consented", True)
        assert version.consent_via_grant == bea.user_id
        page = await _page(world)
        from app.services.artifact_consent import owner_membership_id

        assert version.consented_by_membership_id == await owner_membership_id(db, page)
        assert await _pending(world, ShareRequestKind.VERSION) == []
        entry = [
            details
            for action, details in await _actions(db, page.id)
            if action == "artifact.data_consented" and details.get("via_grant")
        ]
        assert entry[0]["via_grant"] == str(bea.user_id)

    async def test_the_owner_s_strip_says_whose_grant_consented_and_what_grew(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        detail = await world.service.read(world.olga, world.page_id)  # type: ignore[arg-type]

        assert detail.consent is not None
        beas_email = (await db.get(User, bea.user_id)).email  # type: ignore[union-attr]
        assert (detail.consent.automatic, detail.consent.via) == (True, beas_email)
        assert detail.consent.grown == ["+Quantity"]
        assert detail.may_grant_edit_data is True
        editors = await world.service.read(bea, world.page_id)  # type: ignore[arg-type]
        assert editors.may_grant_edit_data is False

    async def test_a_grant_through_a_group_counts_the_same(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(reads_table=True)
        group = await _group_of(world, bea)
        await SharingService(db).share_with_group(
            world.olga,
            await _page(world),
            resource_type=ARTIFACT,
            group_id=group.id,
            level=GrantLevel.EDIT_DATA,
            confirmed=EDIT_DATA_GROUP_WORDING,
        )

        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        version = await world.version(2)
        assert (version.consent_state, version.consent_via_grant) == ("consented", bea.user_id)

    @pytest.mark.security
    async def test_a_plain_editor_s_republish_still_waits_for_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)

        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        version = await world.version(2)
        assert (version.consent_state, version.consent_via_grant) == ("pending", None)

    @pytest.mark.security
    async def test_the_same_checks_as_any_publish_still_apply(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT)  # reads no table
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        with pytest.raises(BadRequestError):
            await world.publish("<p>v2</p>", fields=WIDER, by=bea)

    @pytest.mark.security
    async def test_an_impersonated_holder_is_not_consented(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        set_impersonator(uuid.uuid4())
        try:
            await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        finally:
            set_impersonator(None)

        assert (await world.version(2)).consent_state == "pending"


class TestItDropsWhenTheOwnerGoes:
    async def _two_grants(self, world: _World) -> tuple[AuthContext, AuthContext, Group]:
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        cal = await world.member(page=GrantLevel.EDIT)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)
        group = await _group_of(world, cal)
        await SharingService(world.db).share_with_group(
            world.olga,
            await _page(world),
            resource_type=ARTIFACT,
            group_id=group.id,
            level=GrantLevel.EDIT_DATA,
            confirmed=EDIT_DATA_GROUP_WORDING,
        )
        return bea, cal, group

    async def test_an_ownership_switch_lowers_every_edit_data_grant_to_edit(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea, _cal, group = await self._two_grants(world)
        new_owner = await world.member(reads_table=True)

        await world.service.change_owner(
            world.olga,
            world.page_id,
            ArtifactOwnerUpdate(user_id=new_owner.user_id),  # type: ignore[arg-type]
        )

        assert await _level(world, bea) == "edit"
        grants = await resource_grant_repo.list_for_resource(
            db,
            organization_id=world.org.id,
            resource_type="artifact",
            resource_id=world.page_id,  # type: ignore[arg-type]
        )
        assert {grant.level for grant in grants} == {"edit"}
        [(_, details)] = [
            entry
            for entry in await _actions(db, world.page_id)  # type: ignore[arg-type]
            if entry[0] == "artifact.owner_changed"
        ]
        assert details["edit_data_lowered"] == 2

    async def test_a_withdrawal_lowers_the_grants_so_a_data_editor_s_republish_waits(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        await _grant(world, bea, GrantLevel.EDIT_DATA, confirmed=EDIT_DATA_PERSON_WORDING)

        assert world.page_id is not None
        await world.service.withdraw_consent(world.olga, world.page_id)

        assert await _level(world, bea) == "edit"
        details = [
            details
            for action, details in await _actions(db, world.page_id)
            if action == "artifact.data_withdrawn"
        ]
        assert details[0]["edit_data_lowered"] == 1
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        assert (await world.version(2)).consent_state == "pending"

    async def test_the_new_owner_s_first_republish_by_a_lowered_editor_waits(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea, _cal, _group = await self._two_grants(world)
        new_owner = await world.member(reads_table=True)
        await world.service.change_owner(
            world.olga,
            world.page_id,
            ArtifactOwnerUpdate(user_id=new_owner.user_id),  # type: ignore[arg-type]
        )

        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        assert (await world.version(2)).consent_state == "pending"

    async def test_removing_the_owner_lowers_the_grants_on_their_pages_only(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea, _cal, _group = await self._two_grants(world)
        other = Artifact(
            organization_id=world.org.id,
            owner_user_id=bea.user_id,
            agent_id=world.agent.id,
            name="other",
            title="Other",
            visibility="private",
        )
        db.add(other)
        await db.flush()
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=world.olga.user_id,  # type: ignore[arg-type]
            resource_type="artifact",
            resource_id=other.id,
            level=GrantLevel.EDIT_DATA,
        )
        boss = world.org.created_by_user_id

        await MemberService(db).remove(world.org.id, world.olga.user_id, boss)  # type: ignore[arg-type]

        assert await _level(world, bea) == "edit"
        kept = await resource_grant_repo.get_level(
            db,
            organization_id=world.org.id,
            subject_user_id=world.olga.user_id,  # type: ignore[arg-type]
            resource_type="artifact",
            resource_id=other.id,
        )
        assert kept is GrantLevel.EDIT_DATA

    async def test_the_owner_leaving_does_the_same(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea, _cal, _group = await self._two_grants(world)

        await MemberService(db).leave(world.org.id, world.olga.user_id)  # type: ignore[arg-type]

        assert await _level(world, bea) == "edit"


async def _share(
    world: _World,
    by: AuthContext,
    *,
    visibility: Visibility | None = None,
    people: list[str] | None = None,
    room: bool = False,
) -> artifacts.RunShare:
    return await artifacts.request_share_with(
        world.db,
        organization_id=world.org.id,
        agent_id=world.agent.id,
        run_person=by.user_id,  # type: ignore[arg-type]
        run_id=None,
        name="pipeline",
        visibility=visibility,
        people=people or [],
        room=room,
    )


class TestAskingToShareFromARun:
    async def test_the_owner_s_own_run_files_a_request_and_applies_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        olga = await db.get(User, world.olga.user_id)
        assert olga is not None
        olga.full_name = "Olga Ng"

        shared = await _share(world, world.olga, visibility=Visibility.ORG)

        assert (shared.filed, shared.asked, shared.waiting_for) == (True, ["org"], "Olga Ng")
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        assert request.requested_visibility == "org"
        assert request.requester_user_id == world.olga.user_id
        page = await _page(world)
        assert (page.visibility, page.public_key) == ("private", None)

    async def test_people_and_groups_are_found_by_name_or_address_and_asked_view_only(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        ada = await world.member()
        grace = await world.member()
        assert ada.user_id and grace.user_id
        ada_user, grace_user = await db.get(User, ada.user_id), await db.get(User, grace.user_id)
        assert ada_user is not None and grace_user is not None
        ada_user.full_name = "Ada Lovelace"
        group = await _group_of(world, name="Sales")

        shared = await _share(
            world,
            world.olga,
            people=["ada lovelace", grace_user.email.upper(), "sales", "ada lovelace"],
        )

        assert shared.asked == ["Ada Lovelace", grace_user.email, "Sales"]
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        assert request.requested_subjects == {
            "people": [
                {"user_id": str(ada.user_id), "level": "read"},
                {"user_id": str(grace.user_id), "level": "read"},
            ],
            "groups": [{"group_id": str(group.id), "level": "read"}],
        }

    async def test_a_name_nobody_or_several_members_have_is_reported_and_left_out(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        for _ in range(2):
            twin = await world.member()
            user = await db.get(User, twin.user_id)
            assert user is not None
            user.full_name = "Sam Twin"

        shared = await _share(
            world, world.olga, visibility=Visibility.TEAM, people=["Sam Twin", "Nobody"]
        )

        assert (shared.unknown, shared.ambiguous, shared.asked) == (
            ["Nobody"],
            ["Sam Twin"],
            ["team"],
        )

    async def test_what_the_page_is_shared_with_already_is_left_out_and_no_request_is_filed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        await world.share_with_everyone()

        shared = await _share(world, world.olga, visibility=Visibility.ORG)

        assert (shared.filed, shared.already, shared.waiting_for) == (False, ["org"], None)
        assert await _pending(world, ShareRequestKind.AUDIENCE) == []

    async def test_an_editor_asks_the_owner_and_a_second_ask_carries_the_first(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann = await world.member()
        ann_user = await db.get(User, ann.user_id)
        assert ann_user is not None

        await _share(world, bea, visibility=Visibility.TEAM)
        shared = await _share(world, bea, people=[ann_user.email])

        assert shared.waiting_for == (await db.get(User, world.olga.user_id)).email  # type: ignore[union-attr]
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        assert request.requested_visibility == "team"
        assert len(request.requested_subjects["people"]) == 1  # type: ignore[index]

    async def test_a_page_with_no_owner_waits_for_an_owner_or_admin(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        (await _page(world)).owner_user_id = None
        await db.flush()

        shared = await _share(world, bea, visibility=Visibility.ORG)

        assert (shared.filed, shared.waiting_for) == (True, None)

    async def test_a_deactivated_owner_s_run_is_refused_not_crashed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        olga = await db.get(User, world.olga.user_id)
        assert olga is not None
        olga.is_active = False
        await db.flush()

        with pytest.raises(AuthorizationError):
            await _share(world, world.olga, visibility=Visibility.ORG)
        assert await _pending(world, ShareRequestKind.AUDIENCE) == []

    async def test_an_editor_does_not_wait_for_an_owner_who_has_left(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        olga = await db.get(User, world.olga.user_id)
        assert olga is not None
        olga.is_active = False
        await db.flush()

        shared = await _share(world, bea, visibility=Visibility.ORG)

        assert (shared.filed, shared.waiting_for) == (True, None)

    async def test_the_owner_and_the_run_s_person_are_not_asked_for_and_the_audit_names_the_run(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann = await world.member()
        olga, bea_user, ann_user = (
            await db.get(User, world.olga.user_id),
            await db.get(User, bea.user_id),
            await db.get(User, ann.user_id),
        )
        assert olga and bea_user and ann_user
        run_id = uuid.uuid4()

        shared = await artifacts.request_share_with(
            db,
            organization_id=world.org.id,
            agent_id=world.agent.id,
            run_person=bea.user_id,  # type: ignore[arg-type]
            run_id=run_id,
            name="pipeline",
            visibility=None,
            people=[olga.email, bea_user.email, ann_user.email],
        )

        assert shared.asked == [ann_user.email]
        row = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "artifact.share_requested",
                    AppAdminAuditLog.organization_id == world.org.id,
                )
            )
        ).scalar_one()
        assert row.details["run_id"] == str(run_id)
        assert row.details["agent_id"] == str(world.agent.id)

    async def test_a_person_and_a_group_with_one_name_are_ambiguous(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        ada = await world.member()
        ada_user = await db.get(User, ada.user_id)
        assert ada_user is not None
        ada_user.full_name = "Sales"
        await _group_of(world, name="Sales")

        shared = await _share(world, world.olga, people=["sales"])

        assert (shared.ambiguous, shared.filed) == (["sales"], False)

    @pytest.mark.security
    async def test_somebody_who_may_only_view_it_cannot_ask_and_a_stranger_cannot_tell_it_exists(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        reader = await world.member(page=GrantLevel.READ)
        stranger = await world.member()

        with pytest.raises(AuthorizationError):
            await _share(world, reader, visibility=Visibility.ORG)
        with pytest.raises(NotFoundError):
            await _share(world, stranger, visibility=Visibility.ORG)
        assert await _pending(world, ShareRequestKind.AUDIENCE) == []

    @pytest.mark.security
    async def test_a_group_chat_reaches_only_organization_wide_pages(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)

        with pytest.raises(NotFoundError):
            await _share(world, world.olga, people=["x"], room=True)
        await world.share_with_everyone()
        shared = await _share(world, world.olga, people=["x"], room=True)
        assert shared.unknown == ["x"]

    async def test_an_archived_page_is_not_there_and_a_vanished_one_is_not_either(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await _consented(world)
        (await _page(world)).archived_at = datetime.now(UTC)
        await db.flush()

        with pytest.raises(NotFoundError):
            await _share(world, world.olga, visibility=Visibility.ORG)


class TestAdmitting:
    async def test_the_filing_refuses_a_page_archived_between_the_read_and_the_lock(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        from app.services.artifact_requests import file_audience_request
        from app.services.sharing import ShareChange

        world = await _world(db)
        await _consented(world)
        page = await _page(world)
        page.archived_at = datetime.now(UTC)
        with pytest.raises(ConflictError):
            await file_audience_request(
                db, world.olga, page, [ShareChange(visibility=Visibility.ORG)]
            )
