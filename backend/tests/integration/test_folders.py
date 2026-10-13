"""A folder grants access to what it holds, and a subfolder only narrows (#2124).

Against a real database, because the whole of it is a query: the folder's grants
reach the rows filed in it through `resource_grant_repo`, and the folder's
visibility reaches them through the column every listing already filters on.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.group import Group, GroupMember
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.skill import Skill
from app.db.models.user import User
from app.schemas.folder import FolderCreate, FolderUpdate
from app.schemas.resource_grant import AudienceChoice
from app.services.access import SKILL, resolve_access
from app.services.folder import FolderService
from app.services.sharing import SharingService
from app.services.skills import SkillService

pytestmark = pytest.mark.anyio


async def _person(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def _member(
    db: AsyncSession, organization: Organization, role: str = "member"
) -> AuthContext:
    person = await _person(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return AuthContext(user_id=person.id, organization_id=organization.id, role=role)


async def _group(db: AsyncSession, organization: Organization, *people: AuthContext) -> Group:
    group = Group(organization_id=organization.id, name=f"Dept {uuid.uuid4().hex[:6]}")
    db.add(group)
    await db.flush()
    for person in people:
        assert person.user_id is not None
        db.add(GroupMember(group_id=group.id, user_id=person.user_id))
    await db.flush()
    return group


async def _org(db: AsyncSession) -> tuple[Organization, AuthContext]:
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


async def _skill(db: AsyncSession, ctx: AuthContext, name: str) -> Skill:
    return await SkillService(db).create(
        ctx, name=name, description="x", content="x", visibility=Visibility.ORG
    )


async def _names(db: AsyncSession, ctx: AuthContext) -> list[str]:
    return [skill.name for skill in (await SkillService(db).list_readable(ctx)).items]


async def _folder(
    db: AsyncSession, ctx: AuthContext, name: str, *, parent: uuid.UUID | None = None, **audience
):
    return await FolderService(db).create(
        ctx, kind="skill", data=FolderCreate(name=name, parent_id=parent, **audience)
    )


class TestAFolderGrantsAccess:
    async def test_only_the_folders_audience_lists_what_it_holds(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        seller = await _member(db, organization)
        outsider = await _member(db, organization)
        sales = await _group(db, organization, seller)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        playbook = await _skill(db, owner, "playbook")

        await FolderService(db).file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        assert playbook.visibility == Visibility.PRIVATE.value
        assert "playbook" in await _names(db, seller)
        assert "playbook" not in await _names(db, outsider)
        assert await resolve_access(db, seller, playbook, Perm.SKILLS_VIEW, resource_type=SKILL)
        assert not await resolve_access(
            db, outsider, playbook, Perm.SKILLS_VIEW, resource_type=SKILL
        )

    async def test_a_direct_share_still_reaches_somebody_outside_the_folder(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        outsider = await _member(db, organization)
        assert outsider.user_id is not None
        gtm = await _folder(db, owner, "GTM", visibility=Visibility.PRIVATE)
        playbook = await _skill(db, owner, "playbook")
        await FolderService(db).file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        await SharingService(db).share(
            owner,
            playbook,
            resource_type=SKILL,
            subject_user_id=outsider.user_id,
            level=GrantLevel.READ,
        )

        assert "playbook" in await _names(db, outsider)

    async def test_the_folders_audience_uses_what_it_holds_but_cannot_edit_it(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        seller = await _member(db, organization)
        sales = await _group(db, organization, seller)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        playbook = await _skill(db, owner, "playbook")
        await FolderService(db).file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        assert not await resolve_access(db, seller, playbook, Perm.SKILLS_EDIT, resource_type=SKILL)

    async def test_taking_it_out_keeps_who_it_reached(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM", visibility=Visibility.PRIVATE)
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=None)

        assert playbook.folder_id is None
        assert playbook.visibility == Visibility.PRIVATE.value

    async def test_a_filed_resource_cannot_be_widened_past_its_folder(
        self, db: AsyncSession
    ) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM", visibility=Visibility.PRIVATE)
        playbook = await _skill(db, owner, "playbook")
        await FolderService(db).file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        with pytest.raises(BadRequestError):
            await SharingService(db).set_visibility(
                owner, playbook, resource_type=SKILL, visibility=Visibility.ORG
            )

    async def test_somebody_who_cannot_edit_a_resource_cannot_file_it(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        viewer = await _member(db, organization, "viewer")
        gtm = await _folder(db, owner, "GTM")
        playbook = await _skill(db, owner, "playbook")

        with pytest.raises(AuthorizationError):
            await FolderService(db).file(
                ctx=viewer, kind="skill", resource=playbook, folder_id=gtm.id
            )


class TestTheFolderItself:
    async def test_a_restricted_folder_is_not_listed_or_found_by_an_outsider(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        outsider = await _member(db, organization)
        sales = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        service = FolderService(db)

        assert [view.folder.name for view in await service.list(outsider, kind="skill")] == []
        with pytest.raises(NotFoundError):
            await service.get(outsider, kind="skill", folder_id=gtm.id)

    async def test_another_organizations_folder_is_not_found(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        _, stranger = await _org(db)
        gtm = await _folder(db, owner, "GTM")

        with pytest.raises(NotFoundError):
            await FolderService(db).get(stranger, kind="skill", folder_id=gtm.id)

    async def test_a_folder_of_one_kind_is_not_found_as_another(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")

        with pytest.raises(NotFoundError):
            await FolderService(db).get(owner, kind="context", folder_id=gtm.id)

    async def test_its_view_names_its_audience_and_counts_what_it_holds(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        [view] = await service.list(owner, kind="skill")

        assert view.group_ids == [sales.id]
        assert view.item_count == 1
        assert view.can_edit

    async def test_only_an_editor_renames_or_deletes_it(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        member = await _member(db, organization)
        gtm = await _folder(db, owner, "GTM")
        service = FolderService(db)

        with pytest.raises(AuthorizationError):
            await service.update(member, gtm, FolderUpdate(name="Mine"))
        with pytest.raises(AuthorizationError):
            await service.delete(member, gtm, move_to=None)


class TestASubfolderOnlyNarrows:
    async def test_it_cannot_reach_wider_than_its_parent(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        finance = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])

        with pytest.raises(BadRequestError):
            await _folder(db, owner, "Everyone", parent=gtm.id, visibility=Visibility.ORG)
        with pytest.raises(BadRequestError):
            await _folder(db, owner, "Finance", parent=gtm.id, group_ids=[finance.id])

        inbound = await _folder(db, owner, "Inbound", parent=gtm.id, group_ids=[sales.id])
        assert inbound.parent_id == gtm.id

    async def test_anything_fits_under_a_folder_for_everyone(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        everyone = await _folder(db, owner, "Company")

        narrowed = await _folder(db, owner, "Sales", parent=everyone.id, group_ids=[sales.id])

        assert narrowed.visibility == Visibility.PRIVATE.value

    async def test_narrowing_a_parent_narrows_its_subfolders_and_what_they_hold(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        seller = await _member(db, organization)
        sales = await _group(db, organization, seller)
        gtm = await _folder(db, owner, "GTM")
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id)
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=inbound.id)
        assert playbook.visibility == Visibility.ORG.value

        await service.set_audience(owner, gtm, AudienceChoice(group_ids=[sales.id]))
        await db.refresh(inbound)
        await db.refresh(playbook)

        assert inbound.visibility == Visibility.PRIVATE.value
        assert playbook.visibility == Visibility.PRIVATE.value

    async def test_narrowing_drops_a_subfolders_subjects_the_parent_no_longer_names(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        finance = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id, finance.id])
        inbound = await _folder(
            db, owner, "Inbound", parent=gtm.id, group_ids=[sales.id, finance.id]
        )
        service = FolderService(db)

        await service.set_audience(owner, gtm, AudienceChoice(group_ids=[sales.id]))

        [view] = [v for v in await service.list(owner, kind="skill") if v.folder.id == inbound.id]
        assert view.group_ids == [sales.id]

    async def test_moving_a_folder_under_a_narrower_one_narrows_it(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        loose = await _folder(db, owner, "Loose")
        service = FolderService(db)

        moved = await service.update(owner, loose, FolderUpdate(parent_id=gtm.id))

        assert moved.parent_id == gtm.id
        assert moved.visibility == Visibility.PRIVATE.value

    async def test_a_folder_cannot_go_inside_itself(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id)
        service = FolderService(db)

        with pytest.raises(BadRequestError):
            await service.update(owner, gtm, FolderUpdate(parent_id=inbound.id))

    async def test_it_can_be_moved_to_the_top_and_renamed(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id)

        moved = await FolderService(db).update(
            owner, inbound, FolderUpdate(name="Inbound leads", to_top=True)
        )

        assert (moved.parent_id, moved.name) == (None, "Inbound leads")


class TestDeletingAFolder:
    async def test_its_contents_move_where_the_person_says(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        archive = await _folder(db, owner, "Archive", visibility=Visibility.PRIVATE)
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id, group_ids=[sales.id])
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        await service.delete(owner, gtm, move_to=archive.id)
        await db.refresh(playbook)
        await db.refresh(inbound)

        assert playbook.folder_id == archive.id
        assert inbound.parent_id == archive.id
        assert [v.folder.name for v in await service.list(owner, kind="skill")] == [
            "Archive",
            "Inbound",
        ]

    async def test_to_the_top_level_by_default(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)

        await service.delete(owner, gtm, move_to=None)
        await db.refresh(playbook)

        assert playbook.folder_id is None

    async def test_its_contents_cannot_move_into_its_own_subfolder(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id)

        with pytest.raises(BadRequestError):
            await FolderService(db).delete(owner, gtm, move_to=inbound.id)


class TestTheRestOfIt:
    async def test_renaming_alone_leaves_it_where_it_is(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id)
        service = FolderService(db)

        renamed = await service.update(owner, inbound, FolderUpdate(name="Inbound leads"))
        view = await service.view(owner, renamed)

        assert (renamed.parent_id, view.folder.name, view.item_count) == (
            gtm.id,
            "Inbound leads",
            0,
        )
        assert repr(renamed) == f"<Folder(skill:Inbound leads id={renamed.id})>"

    async def test_a_person_dropped_from_the_audience_loses_it(self, db: AsyncSession) -> None:
        organization, owner = await _org(db)
        seller = await _member(db, organization)
        assert seller.user_id is not None
        gtm = await _folder(db, owner, "GTM", user_ids=[seller.user_id])
        playbook = await _skill(db, owner, "playbook")
        service = FolderService(db)
        await service.file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)
        assert "playbook" in await _names(db, seller)

        await service.set_audience(owner, gtm, AudienceChoice(visibility=Visibility.PRIVATE))

        assert "playbook" not in await _names(db, seller)

    async def test_opening_a_folder_to_everyone_leaves_its_subfolders_as_they_were(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        sales = await _group(db, organization)
        gtm = await _folder(db, owner, "GTM", group_ids=[sales.id])
        inbound = await _folder(db, owner, "Inbound", parent=gtm.id, group_ids=[sales.id])
        service = FolderService(db)

        await service.set_audience(owner, gtm, AudienceChoice(visibility=Visibility.ORG))
        await db.refresh(inbound)

        assert inbound.visibility == Visibility.PRIVATE.value

    async def test_something_that_cannot_be_filed_is_refused(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        other = await _folder(db, owner, "Other")

        with pytest.raises(BadRequestError):
            await FolderService(db).file(ctx=owner, kind="skill", resource=other, folder_id=gtm.id)


class TestListingOneFolder:
    async def _listed(self, db: AsyncSession, ctx: AuthContext, folder: str | None) -> list[str]:
        scope = await FolderService(db).scope(ctx, kind="skill", folder=folder)
        listing = await SkillService(db).list_readable(ctx, folder=scope)
        return sorted(skill.name for skill in listing.items)

    async def test_the_top_level_and_a_folder_list_what_each_holds(self, db: AsyncSession) -> None:
        _, owner = await _org(db)
        gtm = await _folder(db, owner, "GTM")
        await _skill(db, owner, "loose")
        filed = await _skill(db, owner, "filed")
        await FolderService(db).file(ctx=owner, kind="skill", resource=filed, folder_id=gtm.id)

        assert await self._listed(db, owner, "top") == ["loose"]
        assert await self._listed(db, owner, str(gtm.id)) == ["filed"]
        assert await self._listed(db, owner, None) == ["filed", "loose"]

    async def test_something_shared_from_a_folder_one_cannot_see_is_at_the_top(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        outsider = await _member(db, organization)
        assert outsider.user_id is not None
        gtm = await _folder(db, owner, "GTM", visibility=Visibility.PRIVATE)
        playbook = await _skill(db, owner, "playbook")
        await FolderService(db).file(ctx=owner, kind="skill", resource=playbook, folder_id=gtm.id)
        await SharingService(db).share(
            owner,
            playbook,
            resource_type=SKILL,
            subject_user_id=outsider.user_id,
            level=GrantLevel.READ,
        )

        assert await self._listed(db, outsider, "top") == ["playbook"]

    async def test_a_folder_named_wrongly_or_out_of_reach_is_refused(
        self, db: AsyncSession
    ) -> None:
        organization, owner = await _org(db)
        outsider = await _member(db, organization)
        gtm = await _folder(db, owner, "GTM", visibility=Visibility.PRIVATE)
        service = FolderService(db)

        with pytest.raises(BadRequestError):
            await service.scope(owner, kind="skill", folder="not-a-folder")
        with pytest.raises(NotFoundError):
            await service.scope(outsider, kind="skill", folder=str(gtm.id))

    async def test_context_and_apps_filter_on_their_folder_too(self, db: AsyncSession) -> None:
        from app.repositories import artifact_repo, context_repo
        from app.repositories.folder import FolderScope

        _, owner = await _org(db)
        assert owner.user_id is not None
        top = FolderScope(folder_id=None, visible=frozenset({uuid.uuid4()}))
        for repo in (context_repo, artifact_repo):
            items, total = await repo.list_visible(
                db,
                organization_id=owner.organization_id,
                user_id=owner.user_id,
                see_all=True,
                shared_ids=[],
                folder=top,
            )
            assert (items, total) == ([], 0)
