"""Handing a page to another owner, on real rows (#1974).

The consent suite's world: a page that belongs to Olga, a Member who reads the orders
table by a grant. Here it changes hands, and these prove what only a database can: the
consents given under the old owner's membership stopping to hold with no write to them,
the audit entry and both notifications, and the sharing layer's adoption of a page
nobody owns being an ownership change - or refused.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.db.models.artifact import Artifact
from app.db.models.notification import Notification
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo
from app.schemas.artifact import ArtifactAutoConsentUpdate, ArtifactOwnerUpdate
from app.services.access import ARTIFACT
from app.services.artifact_consent import AUTO_CONSENT_WORDING
from app.services.artifact_ownership import change_owner
from app.services.file_storage import LocalFileStorage
from app.services.sharing import SharingService
from tests.integration.test_artifact_consent import _actions, _World, _world, storage
from tests.integration.virtual_table_support import make_user

pytestmark = pytest.mark.anyio

__all__ = ["storage"]


@contextmanager
def impersonated() -> Iterator[None]:
    set_impersonator(uuid.uuid4())
    try:
        yield
    finally:
        set_impersonator(None)


async def _page(world: _World) -> Artifact:
    assert world.page_id is not None
    page = await artifact_repo.get(world.db, world.page_id, organization_id=world.org.id)
    assert page is not None
    return page


async def _orphan(world: _World) -> None:
    """The page's owner leaves the organization's users: `SET NULL`, as a deletion does."""
    page = await _page(world)
    page.owner_user_id = None
    await world.db.flush()


async def _notified(db: AsyncSession, page: Artifact) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(Notification.recipient_user_id, Notification.summary).where(
            Notification.event_type == "artifact_owner_changed",
            Notification.render_context["artifact_id"].astext == str(page.id),
        )
    )
    return dict(rows.all())


class TestTheOwnerHandsItOver:
    async def test_the_owner_hands_the_page_to_an_active_member(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None

        detail = await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        assert detail.owner_user_id == bea.user_id
        assert detail.may_change_owner is False
        [(action, details)] = [
            entry
            for entry in await _actions(db, published.artifact_id)
            if entry[0] == "artifact.owner_changed"
        ]
        assert details["from"] == str(world.olga.user_id)
        assert (details["to"], details["by"]) == (str(bea.user_id), str(world.olga.user_id))

    async def test_both_owners_are_told_which_page_and_who_switched_never_its_data(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None and world.olga.user_id is not None

        await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        told = await _notified(db, await _page(world))
        # The one who switched is never told of their own act.
        assert set(told) == {bea.user_id}
        assert "Pipeline" in told[bea.user_id]
        assert "confirm" in told[bea.user_id]
        assert "Ann" not in "".join(told.values())

    async def test_an_admin_switching_tells_the_old_and_the_new_owner_not_themselves(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        admin = await world.member(role="admin")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None and world.olga.user_id is not None

        await world.service.change_owner(
            admin, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        told = await _notified(db, await _page(world))
        assert set(told) == {world.olga.user_id, bea.user_id}
        assert "Pipeline" in told[world.olga.user_id]

    async def test_auto_consent_goes_back_off(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.service.set_auto_consent(
            world.olga,
            published.artifact_id,
            ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
        )
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None

        await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        assert (await _page(world)).auto_consent is False

    @pytest.mark.security
    async def test_the_audience_waits_for_the_new_owner_who_can_confirm(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """No consent is written to or deleted: they name the old membership."""
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        await world.confirm(world.olga, 1)
        reader = await world.member(role="viewer")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None
        assert await world.served(reader) == (1, "ok")

        await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )
        assert await world.served(reader) == (1, "awaiting_consent")

        await world.confirm(bea, 1)
        assert await world.served(reader) == (1, "ok")

    @pytest.mark.security
    async def test_handing_back_does_not_revive_the_first_owners_consent(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """A -> B -> A: every switch voids every consent so far, for good."""
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        await world.confirm(world.olga, 1)
        reader = await world.member(role="viewer")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None and world.olga.user_id is not None
        assert await world.served(reader) == (1, "ok")

        await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )
        await world.service.change_owner(
            bea, published.artifact_id, ArtifactOwnerUpdate(user_id=world.olga.user_id)
        )

        assert (await _page(world)).owner_user_id == world.olga.user_id
        assert await world.served(reader) == (1, "awaiting_consent")
        await world.confirm(world.olga, 1)
        assert await world.served(reader) == (1, "ok")

    @pytest.mark.security
    async def test_a_switch_committed_between_the_read_and_the_lock_refuses_the_old_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """Olga's request read the page as hers; Bea's took it before Olga's lock."""
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        cleo = await world.member(reads_table=True)
        assert bea.user_id is not None and cleo.user_id is not None
        stale = await _page(world)
        await db.execute(
            update(Artifact).where(Artifact.id == stale.id).values(owner_user_id=bea.user_id)
        )

        with pytest.raises(AuthorizationError):
            await change_owner(db, world.olga, stale, new_owner_user_id=cleo.user_id)

        assert (await _page(world)).owner_user_id == bea.user_id

    @pytest.mark.security
    async def test_a_confirm_after_a_concurrent_switch_records_nothing_for_the_old_owner(
        self, db: AsyncSession, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None
        original_lock = artifact_repo.lock

        async def lock_after_a_switch(session: AsyncSession, artifact_id: uuid.UUID):
            await session.execute(
                update(Artifact).where(Artifact.id == artifact_id).values(owner_user_id=bea.user_id)
            )
            return await original_lock(session, artifact_id)

        monkeypatch.setattr(artifact_repo, "lock", lock_after_a_switch)
        with pytest.raises(AuthorizationError):
            await world.confirm(world.olga, 1)

        assert (await world.version(1)).consent_state != "consented"

    @pytest.mark.security
    async def test_auto_consent_is_the_current_owners_call_on_the_locked_row(
        self, db: AsyncSession, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None
        original_lock = artifact_repo.lock

        async def lock_after_a_switch(session: AsyncSession, artifact_id: uuid.UUID):
            # Another request switches the owner between the service's read and its lock.
            await session.execute(
                update(Artifact).where(Artifact.id == artifact_id).values(owner_user_id=bea.user_id)
            )
            return await original_lock(session, artifact_id)

        monkeypatch.setattr(artifact_repo, "lock", lock_after_a_switch)
        with pytest.raises(AuthorizationError):
            await world.service.set_auto_consent(
                world.olga,
                published.artifact_id,
                ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
            )

        assert (await _page(world)).auto_consent is False

    @pytest.mark.security
    async def test_the_old_owner_may_not_hand_it_over_again(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None
        await world.service.change_owner(
            world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        # A Member with no grant on a private page: it is no longer hers to open.
        with pytest.raises(NotFoundError):
            await world.service.change_owner(
                world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
            )


class TestAnAdminReassigns:
    async def test_an_admin_takes_a_page_whose_owner_is_gone(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        await _orphan(world)
        admin = await world.member(role="admin")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None

        detail = await world.service.change_owner(
            admin, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        assert detail.owner_user_id == bea.user_id
        [(_, details)] = [
            entry
            for entry in await _actions(db, published.artifact_id)
            if entry[0] == "artifact.owner_changed"
        ]
        assert (details["from"], details["by"]) == (None, str(admin.user_id))
        assert set(await _notified(db, await _page(world))) == {bea.user_id}

    @pytest.mark.security
    async def test_a_grant_to_edit_is_no_authority_over_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        editor = await world.member(page=GrantLevel.EDIT)
        assert editor.user_id is not None

        with pytest.raises(AuthorizationError):
            await world.service.change_owner(
                editor, published.artifact_id, ArtifactOwnerUpdate(user_id=editor.user_id)
            )

        assert (await _page(world)).owner_user_id == world.olga.user_id
        detail = await world.service.read(editor, published.artifact_id)
        assert detail.may_change_owner is False

    @pytest.mark.security
    async def test_nobody_impersonated_changes_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        bea = await world.member(reads_table=True)
        assert bea.user_id is not None

        with impersonated(), pytest.raises(AuthorizationError):
            await world.service.change_owner(
                world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=bea.user_id)
            )

        assert (await _page(world)).owner_user_id == world.olga.user_id

    async def test_the_new_owner_must_be_an_active_member_of_the_organization(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        outsider = await make_user(db)
        deactivated = await world.member()
        assert deactivated.user_id is not None
        await db.execute(update(User).where(User.id == deactivated.user_id).values(is_active=False))

        for target in (outsider.id, deactivated.user_id, uuid.uuid4()):
            with pytest.raises(BadRequestError):
                await world.service.change_owner(
                    world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=target)
                )
        assert world.olga.user_id is not None
        with pytest.raises(BadRequestError, match="already owns"):
            await world.service.change_owner(
                world.olga, published.artifact_id, ArtifactOwnerUpdate(user_id=world.olga.user_id)
            )

        assert (await _page(world)).owner_user_id == world.olga.user_id

    async def test_the_server_says_who_may_hand_the_page_over(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        published = await world.publish("<p>v1</p>")
        admin = await world.member(role="admin")
        reader = await world.member(page=GrantLevel.READ)

        flags = {
            who: (await world.service.read(ctx, published.artifact_id)).may_change_owner
            for who, ctx in {"owner": world.olga, "admin": admin, "reader": reader}.items()
        }

        assert flags == {"owner": True, "admin": True, "reader": False}


class TestAdoptingAPageNobodyOwns:
    async def _orphaned(self, world: _World) -> Artifact:
        await world.publish("<p>v1</p>")
        await _orphan(world)
        page = await _page(world)
        page.visibility = Visibility.ORG.value
        await world.db.flush()
        return page

    async def test_an_admin_going_private_becomes_the_owner_with_every_effect(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        page = await self._orphaned(world)
        page.auto_consent = True
        admin = await world.member(role="admin")

        await SharingService(db).set_visibility(
            admin, page, resource_type=ARTIFACT, visibility=Visibility.PRIVATE
        )

        assert (page.owner_user_id, page.auto_consent) == (admin.user_id, False)
        actions = [action for action, _ in await _actions(db, page.id)]
        assert "artifact.owner_changed" in actions
        assert "resource.owner_claimed" not in actions
        # The admin is the only one it concerns, and never told of their own act.
        assert await _notified(db, page) == {}

    async def test_an_admin_who_is_no_member_cannot_adopt_with_a_plain_refusal(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        page = await self._orphaned(world)
        admin = await world.member(role="admin")
        stranger = await make_user(db)
        outside = replace(admin, user_id=stranger.id)

        with pytest.raises(BadRequestError, match="Only a member") as refused:
            await SharingService(db).set_visibility(
                outside, page, resource_type=ARTIFACT, visibility=Visibility.PRIVATE
            )

        # There is no `user_id` in that request, so nothing names a field.
        assert "fields" not in (refused.value.details or {})
        assert page.owner_user_id is None

    @pytest.mark.security
    async def test_a_grant_editor_cannot_adopt_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        page = await self._orphaned(world)
        editor = await world.member(page=GrantLevel.EDIT)

        with pytest.raises(AuthorizationError):
            await SharingService(db).set_visibility(
                editor, page, resource_type=ARTIFACT, visibility=Visibility.PRIVATE
            )

        assert (page.owner_user_id, page.visibility) == (None, "org")

    async def test_widening_an_ownerless_page_needs_no_adoption(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        page = await self._orphaned(world)
        admin = await world.member(role="admin")

        await SharingService(db).set_visibility(
            admin, page, resource_type=ARTIFACT, visibility=Visibility.TEAM
        )

        assert (page.owner_user_id, page.visibility) == (None, "team")
