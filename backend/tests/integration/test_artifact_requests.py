"""Requests to share a page, or to confirm a version of it, on real rows (#1974).

The consent suite's world: a page that belongs to Olga, a Member who reads the orders
table by a grant, here with the people who would ask her: Bea, an editor by grant who
reads the table too; Carl, a Viewer who cannot open the page; and the roles that edit
every page. These prove what only a database can: the one pending request per person and
kind the partial unique indexes hold, a newer request replacing an older one under the
page's lock, requests voided by what changes under them, and who is told.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import set_impersonator
from app.core.config import settings
from app.core.exceptions import (
    AccessRequestableError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    ConsentRequiredError,
    NotFoundError,
    RateLimitError,
)
from app.core.permissions import AuthContext
from app.db.models.artifact import Artifact
from app.db.models.artifact_share_request import (
    ArtifactShareRequest,
    ShareRequestKind,
    ShareRequestStatus,
)
from app.db.models.group import Group
from app.db.models.notification import Notification
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo, artifact_share_request_repo, resource_grant_repo
from app.schemas.artifact import ArtifactOwnerUpdate
from app.schemas.artifact_share_request import ArtifactAccessRequestCreate, ArtifactAccessRequested
from app.services.access import ARTIFACT
from app.services.artifact_request_service import ArtifactRequestService
from app.services.artifact_requests import file_access_request
from app.services.file_storage import LocalFileStorage
from app.services.notification_center import NotificationCenterService
from app.services.sharing import Deferred, SharingService
from tests.integration.test_artifact_consent import (
    WIDER,
    _actions,
    _World,
    _world,
    storage,
)
from tests.integration.virtual_table_support import make_org, make_user

pytestmark = pytest.mark.anyio

__all__ = ["storage"]

FEWER = {"quantity": "Quantity"}


def _requests(world: _World) -> ArtifactRequestService:
    return ArtifactRequestService(world.db)


async def _page(world: _World) -> Artifact:
    assert world.page_id is not None
    page = await artifact_repo.get(world.db, world.page_id, organization_id=world.org.id)
    assert page is not None
    return page


async def _all(
    world: _World, *, kind: ShareRequestKind | None = None
) -> list[ArtifactShareRequest]:
    assert world.page_id is not None
    return await artifact_share_request_repo.list_for_artifact(
        world.db,
        world.page_id,
        pending_only=False,
        kinds=None if kind is None else [kind],
    )


async def _pending(world: _World, kind: ShareRequestKind) -> list[ArtifactShareRequest]:
    return [r for r in await _all(world, kind=kind) if r.status == "pending"]


async def _told(db: AsyncSession, page: Artifact) -> dict[uuid.UUID, str]:
    rows = await db.execute(
        select(Notification.recipient_user_id, Notification.summary).where(
            Notification.event_type == "artifact_share_requested",
            Notification.render_context["artifact_id"].astext == str(page.id),
        )
    )
    return dict(rows.all())


async def _bound_and_shared(world: _World) -> AuthContext:
    """Olga's page, bound, confirmed and open to the whole organization; Bea edits it."""
    await world.publish("<p>v1</p>")
    await world.confirm(world.olga, 1)
    await world.share_with_everyone()
    return await world.member(page=GrantLevel.EDIT, reads_table=True)


class TestAnEditorsRepublishAsksTheOwner:
    async def test_a_republish_that_changes_the_queries_files_a_version_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)

        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        [request] = await _pending(world, ShareRequestKind.VERSION)
        version = await world.version(2)
        assert request.requester_user_id == bea.user_id
        assert request.version_id == version.id
        assert request.query_fingerprint == version.query_fingerprint
        assert (await world.version(2)).consent_state == "pending"
        told = await _told(db, await _page(world))
        assert set(told) == {world.olga.user_id}
        assert "Pipeline" in told[world.olga.user_id]
        assert "Ann" not in told[world.olga.user_id]  # a name, never what the data holds

    async def test_a_newer_republish_replaces_the_older_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        await world.publish("<p>v3</p>", fields=FEWER, by=bea)

        everything = await _all(world, kind=ShareRequestKind.VERSION)
        by_version = {r.version_id: r for r in everything}
        older, newer = (
            by_version[(await world.version(2)).id],
            by_version[(await world.version(3)).id],
        )
        assert (older.status, older.void_reason) == ("voided", "replaced")
        assert newer.status == "pending"

    async def test_the_owners_own_publish_voids_it_and_asks_nobody(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        await world.publish("<p>v3</p>", fields=FEWER)

        [only] = await _all(world, kind=ShareRequestKind.VERSION)
        assert (only.status, only.void_reason) == ("voided", "superseded")

    async def test_a_republish_nobody_has_to_confirm_asks_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)

        await world.publish("<p>v2</p>", by=bea)  # the consented query: automatic
        await world.publish("<p>v2</p>", by=bea)  # the same bytes: no version at all
        await world.publish("<p>v3</p>", fields=None, by=bea)  # reads nothing now

        assert await _all(world, kind=ShareRequestKind.VERSION) == []

    async def test_approving_confirms_that_versions_data(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        reader = await world.member(role="viewer")
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [request] = await _pending(world, ShareRequestKind.VERSION)
        assert await world.served(reader) == (1, "ok")

        decided = await _requests(world).approve(world.olga, world.page_id, request.id)

        assert (decided.status, decided.can_decide) == (ShareRequestStatus.APPROVED, False)
        assert decided.decided_by_user_id == world.olga.user_id
        assert (await world.version(2)).consent_state == "consented"
        assert await world.served(reader) == (2, "ok")
        assert "artifact.share_request_approved" in [
            a for a, _ in await _actions(db, world.page_id)
        ]

    async def test_confirming_from_the_page_answers_the_request_too(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        await world.confirm(world.olga, 2)

        [request] = await _all(world, kind=ShareRequestKind.VERSION)
        assert (request.status, request.decided_by_user_id) == ("approved", world.olga.user_id)

    async def test_declining_marks_the_version_and_the_audience_keeps_its_own(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        reader = await world.member(role="viewer")
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [request] = await _pending(world, ShareRequestKind.VERSION)

        await _requests(world).decline(world.olga, world.page_id, request.id)

        assert (await world.version(2)).consent_state == "declined"
        assert await world.served(reader) == (1, "ok")
        # A later republish is a request of its own.
        await world.publish("<p>v3</p>", fields=FEWER, by=bea)
        assert len(await _pending(world, ShareRequestKind.VERSION)) == 1

    async def test_an_admin_decides_for_the_owner_and_the_requester_cannot(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        admin = await world.member(role="admin")
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [request] = await _pending(world, ShareRequestKind.VERSION)

        with pytest.raises(AuthorizationError):
            await _requests(world).approve(bea, world.page_id, request.id)
        assert (await _pending(world, ShareRequestKind.VERSION))[0].id == request.id

        await _requests(world).approve(admin, world.page_id, request.id)

        assert (await world.version(2)).consent_state == "consented"

    async def test_a_decided_request_cannot_be_decided_again(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [request] = await _pending(world, ShareRequestKind.VERSION)
        await _requests(world).decline(world.olga, world.page_id, request.id)

        with pytest.raises(ConcurrentChangeError):
            await _requests(world).approve(world.olga, world.page_id, request.id)
        with pytest.raises(NotFoundError):
            await _requests(world).approve(world.olga, world.page_id, uuid.uuid4())

    async def test_the_database_holds_one_pending_version_request_per_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [first] = await _pending(world, ShareRequestKind.VERSION)

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await artifact_share_request_repo.create(
                    db,
                    organization_id=world.org.id,
                    artifact_id=first.artifact_id,
                    kind="version",
                    requester_user_id=world.olga.user_id,
                )


class TestReviewingAVersionChange:
    async def test_the_owner_reads_what_the_new_version_adds(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        review = await _requests(world).review(
            world.olga, world.page_id, (await world.version(2)).id
        )

        assert (review.version.number, review.compared_to, review.widens) == (2, 1, True)
        assert review.publisher_name is not None
        [binding] = review.bindings
        assert (binding.name, binding.change, binding.effect) == ("orders", "changed", "widens")
        [change] = binding.changes
        assert (change.aspect, change.change, change.effect) == ("field", "added", "widens")
        assert review.unchanged == []

    async def test_only_who_may_confirm_reads_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        with pytest.raises(AuthorizationError):
            await _requests(world).review(bea, world.page_id, (await world.version(2)).id)

    async def test_a_binding_the_audience_never_had_is_added_whole(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>", fields=None)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        await world.publish("<p>v2</p>", by=bea)

        review = await _requests(world).review(
            world.olga, world.page_id, (await world.version(2)).id
        )

        [binding] = review.bindings
        assert (binding.change, binding.effect) == ("added", "widens")
        assert binding.parts is not None and binding.parts.table


class TestAnEditorWidensABoundPage:
    async def test_it_becomes_a_request_and_nothing_is_applied(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        page = await _page(world)

        outcome = await SharingService(db).set_visibility(
            bea, page, resource_type=ARTIFACT, visibility=Visibility.ORG
        )

        assert isinstance(outcome, Deferred) and outcome.waiting_for is not None
        assert page.visibility == "private"
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        assert outcome.request_id == request.id and request.requested_visibility == "org"
        assert (request.requester_user_id, request.query_fingerprint) == (
            bea.user_id,
            (await world.version(1)).query_fingerprint,
        )
        assert set(await _told(db, page)) == {world.olga.user_id}
        assert (await world.version(1)).consent_state == "pending"

    async def test_a_second_request_replaces_the_first_and_carries_both(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann, cal = await world.member(), await world.member()
        group = Group(organization_id=world.org.id, name="Sales")
        db.add(group)
        await db.flush()
        page = await _page(world)
        sharing = SharingService(db)
        assert ann.user_id and cal.user_id

        await sharing.share(
            bea, page, resource_type=ARTIFACT, subject_user_id=ann.user_id, level=GrantLevel.READ
        )
        await sharing.share(
            bea, page, resource_type=ARTIFACT, subject_user_id=cal.user_id, level=GrantLevel.USE
        )
        await sharing.share(
            bea, page, resource_type=ARTIFACT, subject_user_id=ann.user_id, level=GrantLevel.EDIT
        )
        await sharing.share(  # lower than what she asked for already: the higher stays
            bea, page, resource_type=ARTIFACT, subject_user_id=ann.user_id, level=GrantLevel.READ
        )
        await sharing.share_with_group(
            bea, page, resource_type=ARTIFACT, group_id=group.id, level=GrantLevel.READ
        )
        await sharing.set_visibility(bea, page, resource_type=ARTIFACT, visibility=Visibility.TEAM)
        await sharing.set_visibility(bea, page, resource_type=ARTIFACT, visibility=Visibility.ORG)
        await sharing.set_visibility(bea, page, resource_type=ARTIFACT, visibility=Visibility.TEAM)

        [pending] = await _pending(world, ShareRequestKind.AUDIENCE)
        assert pending.requested_visibility == "org"
        assert pending.requested_subjects == {
            "people": [
                {"user_id": str(ann.user_id), "level": "edit"},
                {"user_id": str(cal.user_id), "level": "use"},
            ],
            "groups": [{"group_id": str(group.id), "level": "read"}],
        }
        replaced = [r for r in await _all(world) if r.status == "voided"]
        assert {r.void_reason for r in replaced} == {"replaced"}
        grants = await resource_grant_repo.list_for_resource(
            db, organization_id=world.org.id, resource_type=ARTIFACT.key, resource_id=page.id
        )
        assert [grant.subject_user_id for grant in grants] == [bea.user_id]  # her own, to edit

    async def test_narrowing_and_revoking_stay_open_to_every_editor(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.share_with_everyone()
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann = await world.member()
        assert ann.user_id
        page = await _page(world)
        sharing = SharingService(db)
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=ann.user_id,
            resource_type=ARTIFACT.key,
            resource_id=page.id,
            level=GrantLevel.EDIT,
        )

        narrowed = await sharing.set_visibility(
            bea, page, resource_type=ARTIFACT, visibility=Visibility.PRIVATE
        )
        lowered = await sharing.share(
            bea, page, resource_type=ARTIFACT, subject_user_id=ann.user_id, level=GrantLevel.READ
        )
        await sharing.revoke(bea, page, resource_type=ARTIFACT, subject_user_id=ann.user_id)

        assert not isinstance(narrowed, Deferred) and not isinstance(lowered, Deferred)
        assert page.visibility == "private" and lowered.level == "read"
        assert await _all(world) == []

    async def test_a_page_that_reads_no_data_is_shared_by_any_editor(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>plain</p>", fields=None)
        bea = await world.member(page=GrantLevel.EDIT)
        page = await _page(world)

        done = await SharingService(db).set_visibility(
            bea, page, resource_type=ARTIFACT, visibility=Visibility.ORG
        )

        assert not isinstance(done, Deferred) and page.visibility == "org"
        assert await _all(world) == []

    async def test_the_owner_widens_once_the_data_is_confirmed_and_widening_confirms_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        reader = await world.member(role="viewer")
        page = await _page(world)
        with pytest.raises(ConsentRequiredError):
            await SharingService(db).set_visibility(
                world.olga, page, resource_type=ARTIFACT, visibility=Visibility.ORG
            )
        assert (await world.version(1)).consent_state == "pending"
        assert page.visibility == "private"

        await world.confirm(world.olga, 1)
        await SharingService(db).set_visibility(
            world.olga, page, resource_type=ARTIFACT, visibility=Visibility.ORG
        )
        await SharingService(db).share(
            world.olga,
            page,
            resource_type=ARTIFACT,
            subject_user_id=reader.user_id,
            level=GrantLevel.EDIT,
        )

        assert await world.served(reader) == (1, "ok")
        assert (
            len([a for a, _ in await _actions(db, world.page_id) if a == "artifact.data_consented"])
            == 1
        )

    async def test_an_admin_widens_directly_for_the_owner(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        admin = await world.member(role="admin")
        page = await _page(world)

        done = await SharingService(db).set_visibility(
            admin, page, resource_type=ARTIFACT, visibility=Visibility.TEAM
        )

        assert not isinstance(done, Deferred) and page.visibility == "team"

    @pytest.mark.security
    async def test_the_owner_on_somebody_elses_behalf_files_a_request_instead(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        page = await _page(world)
        set_impersonator(uuid.uuid4())
        try:
            outcome = await SharingService(db).set_visibility(
                world.olga, page, resource_type=ARTIFACT, visibility=Visibility.ORG
            )
        finally:
            set_impersonator(None)

        assert isinstance(outcome, Deferred)
        assert page.visibility == "private"

    async def test_widening_is_refused_when_the_owner_cannot_read_the_data(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await resource_grant_repo.revoke(
            db,
            organization_id=world.org.id,
            subject_user_id=world.olga.user_id,
            resource_type="table",
            resource_id=world.table.id,
        )
        page = await _page(world)

        with pytest.raises(ConsentRequiredError):
            await SharingService(db).set_visibility(
                world.olga, page, resource_type=ARTIFACT, visibility=Visibility.ORG
            )

        assert page.visibility == "private"


class TestApprovingAnAudienceRequest:
    async def _asked(
        self, world: _World, bea: AuthContext, who: AuthContext
    ) -> ArtifactShareRequest:
        page = await _page(world)
        sharing = SharingService(world.db)
        await sharing.share(
            bea, page, resource_type=ARTIFACT, subject_user_id=who.user_id, level=GrantLevel.READ
        )
        await sharing.set_visibility(bea, page, resource_type=ARTIFACT, visibility=Visibility.TEAM)
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        return request

    async def test_the_owner_applies_what_was_asked(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann = await world.member()
        group = Group(organization_id=world.org.id, name="Sales")
        db.add(group)
        await db.flush()
        request = await self._asked(world, bea, ann)
        await SharingService(db).share_with_group(
            bea,
            await _page(world),
            resource_type=ARTIFACT,
            group_id=group.id,
            level=GrantLevel.READ,
        )
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)

        decided = await _requests(world).approve(world.olga, world.page_id, request.id)

        page = await _page(world)
        assert page.visibility == "team"
        assert decided.status is ShareRequestStatus.APPROVED
        assert {s.email for s in decided.requested_subjects if s.user_id} == {await _email(db, ann)}
        assert [s.group_name for s in decided.requested_subjects if s.group_id] == ["Sales"]
        assert (
            await resource_grant_repo.get_level(
                db,
                organization_id=world.org.id,
                subject_user_id=ann.user_id,
                resource_type=ARTIFACT.key,
                resource_id=page.id,
            )
            is GrantLevel.READ
        )

    async def test_what_the_owner_already_shared_is_not_narrowed_by_an_older_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        ann = await world.member()
        request = await self._asked(world, bea, ann)
        group = Group(organization_id=world.org.id, name="Ops")
        db.add(group)
        await db.flush()
        page = await _page(world)
        await SharingService(db).share_with_group(
            bea, page, resource_type=ARTIFACT, group_id=group.id, level=GrantLevel.READ
        )
        [request] = await _pending(world, ShareRequestKind.AUDIENCE)
        await resource_grant_repo.upsert_for_group(
            db,
            organization_id=world.org.id,
            subject_group_id=group.id,
            resource_type=ARTIFACT.key,
            resource_id=page.id,
            level=GrantLevel.EDIT,
        )
        page.visibility = "org"
        await db.flush()
        await resource_grant_repo.upsert(
            db,
            organization_id=world.org.id,
            subject_user_id=ann.user_id,
            resource_type=ARTIFACT.key,
            resource_id=page.id,
            level=GrantLevel.EDIT,
        )

        await _requests(world).approve(world.olga, world.page_id, request.id)

        assert page.visibility == "org"
        assert (
            await resource_grant_repo.get_level(
                db,
                organization_id=world.org.id,
                subject_user_id=ann.user_id,
                resource_type=ARTIFACT.key,
                resource_id=page.id,
            )
            is GrantLevel.EDIT
        )

    async def test_a_page_with_no_owner_left_waits_for_nobody_by_name(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        page = await _page(world)
        page.owner_user_id = None
        await db.flush()

        outcome = await SharingService(db).set_visibility(
            bea, page, resource_type=ARTIFACT, visibility=Visibility.ORG
        )

        assert isinstance(outcome, Deferred) and outcome.waiting_for is None
        assert "ArtifactShareRequest" in repr((await _pending(world, ShareRequestKind.AUDIENCE))[0])

    async def test_an_owner_who_has_left_is_not_named_as_the_one_waited_for(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        page = await _page(world)
        owner = await db.get(User, page.owner_user_id)
        assert owner is not None
        owner.is_active = False
        await db.flush()

        outcome = await SharingService(db).set_visibility(
            bea, page, resource_type=ARTIFACT, visibility=Visibility.ORG
        )

        assert isinstance(outcome, Deferred) and outcome.waiting_for is None

    async def test_declining_shares_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        request = await self._asked(world, bea, await world.member())

        decided = await _requests(world).decline(world.olga, world.page_id, request.id)

        assert decided.status is ShareRequestStatus.DECLINED
        assert (await _page(world)).visibility == "private"
        assert (await world.version(1)).consent_state == "pending"
        assert "artifact.share_request_declined" in [
            a for a, _ in await _actions(db, world.page_id)
        ]

    async def test_the_requester_cannot_approve_their_own_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        request = await self._asked(world, bea, await world.member())

        with pytest.raises(AuthorizationError):
            await _requests(world).approve(bea, world.page_id, request.id)
        with pytest.raises(AuthorizationError):
            await _requests(world).decline(bea, world.page_id, request.id)


async def _email(db: AsyncSession, who: AuthContext) -> str:
    from app.db.models.user import User

    user = await db.get(User, who.user_id)
    assert user is not None
    return user.email


class TestRequestsThatGoStale:
    async def test_new_page_queries_void_the_requests_made_about_the_old(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        carl = await world.member(role="viewer")
        await SharingService(db).set_visibility(
            bea, await _page(world), resource_type=ARTIFACT, visibility=Visibility.ORG
        )
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())

        await world.publish("<p>v2</p>", fields=WIDER)

        assert {(r.kind, r.status, r.void_reason) for r in await _all(world)} == {
            ("audience", "voided", "page_changed"),
            ("access", "voided", "page_changed"),
        }

    async def test_a_republish_of_the_same_queries_keeps_them(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())

        await world.publish("<p>v2</p>")

        assert len(await _pending(world, ShareRequestKind.ACCESS)) == 1

    async def test_a_page_that_starts_reading_data_voids_a_plain_access_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>", fields=None)
        carl = await world.member(role="viewer")
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())

        await world.publish("<p>v2</p>")

        [request] = await _all(world, kind=ShareRequestKind.ACCESS)
        assert (request.status, request.void_reason) == ("voided", "page_changed")

    async def test_handing_the_page_over_voids_every_pending_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        carl = await world.member(role="viewer")
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())

        await world.service.change_owner(
            world.olga, world.page_id, ArtifactOwnerUpdate(user_id=bea.user_id)
        )

        assert {(r.status, r.void_reason) for r in await _all(world)} == {
            ("voided", "owner_changed")
        }

    async def test_archiving_the_page_voids_every_pending_request(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)

        await world.service.archive(world.olga, world.page_id)

        assert {(r.status, r.void_reason) for r in await _all(world)} == {("voided", "archived")}


class TestRequestingAccess:
    async def test_a_member_who_cannot_open_the_page_is_told_they_may_ask(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")

        with pytest.raises(AccessRequestableError) as answer:
            await world.service.read(carl, world.page_id)

        assert answer.value.status_code == 403
        # Nothing about the page: its id the caller knew, and whether they asked already.
        assert answer.value.details == {"artifact_id": world.page_id, "requested": False}
        assert "Pipeline" not in answer.value.message
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())
        with pytest.raises(AccessRequestableError) as asked:
            await world.service.read(carl, world.page_id)
        assert (asked.value.details or {})["requested"] is True

    @pytest.mark.security
    async def test_everyone_else_keeps_the_plain_not_found(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        stranger = await make_user(db)
        other = await make_org(db, owner=stranger)
        outsider = AuthContext(user_id=stranger.id, organization_id=other.id, role="owner")
        carl = await world.member(role="viewer")
        nobody = AuthContext(user_id=None, organization_id=world.org.id, role="viewer")
        removed = AuthContext(user_id=uuid.uuid4(), organization_id=world.org.id, role="viewer")

        for caller in (outsider, nobody, removed):
            with pytest.raises(NotFoundError) as refused:
                await world.service.read(caller, world.page_id)
            assert not isinstance(refused.value, AccessRequestableError)
            with pytest.raises(NotFoundError):
                await _requests(world).request_access(
                    caller, world.page_id, ArtifactAccessRequestCreate()
                )

        await world.service.archive(world.olga, world.page_id)
        with pytest.raises(NotFoundError) as archived:
            await world.service.read(carl, world.page_id)
        assert not isinstance(archived.value, AccessRequestableError)
        with pytest.raises(NotFoundError):
            await _requests(world).request_access(
                carl, world.page_id, ArtifactAccessRequestCreate()
            )

    async def test_someone_who_can_open_it_has_nothing_to_ask_for(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        reader = await world.member(role="viewer", page=GrantLevel.READ)

        with pytest.raises(BadRequestError):
            await _requests(world).request_access(
                reader, world.page_id, ArtifactAccessRequestCreate()
            )

    async def test_asking_again_replaces_the_first_and_each_ask_is_limited(
        self, db: AsyncSession, storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR", 2)
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")

        first = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate(note="for the Monday review")
        )
        second = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate(note="please")
        )
        with pytest.raises(RateLimitError):
            await _requests(world).request_access(
                carl, world.page_id, ArtifactAccessRequestCreate()
            )

        assert first.note == "for the Monday review" and second.note == "please"
        [pending] = await _pending(world, ShareRequestKind.ACCESS)
        assert pending.id == second.id
        replaced = {r.id: r.void_reason for r in await _all(world, kind=ShareRequestKind.ACCESS)}
        assert replaced[first.id] == "replaced"

    async def test_the_note_is_held_to_its_length_by_the_database(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await artifact_share_request_repo.create(
                    db,
                    organization_id=world.org.id,
                    artifact_id=world.page_id,
                    kind="access",
                    requester_user_id=world.olga.user_id,
                    note="x" * 501,
                )

    async def test_the_owner_approves_it_and_the_grant_is_applied(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        carl = await world.member(role="viewer")
        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )
        assert carl.user_id
        listed = await _requests(world).list_requests(world.olga, world.page_id)
        assert [(r.id, r.can_decide) for r in listed.items] == [(asked.id, True)]

        await _requests(world).approve(world.olga, world.page_id, asked.id)

        assert (
            await resource_grant_repo.get_level(
                db,
                organization_id=world.org.id,
                subject_user_id=carl.user_id,
                resource_type=ARTIFACT.key,
                resource_id=world.page_id,
            )
            is GrantLevel.READ
        )
        assert await world.served(carl) == (1, "ok")

    async def test_on_a_page_that_reads_no_data_any_editor_may_approve(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>plain</p>", fields=None)
        bea = await world.member(page=GrantLevel.EDIT)
        carl = await world.member(role="viewer")
        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )
        assert [
            r.can_decide for r in (await _requests(world).list_requests(bea, world.page_id)).items
        ] == [True]

        await _requests(world).approve(bea, world.page_id, asked.id)

        assert (await world.service.read(carl, world.page_id)).id == world.page_id

    @pytest.mark.security
    async def test_on_a_page_that_reads_data_an_editor_by_grant_may_not(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        carl = await world.member(role="viewer")
        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )

        assert (await _requests(world).list_requests(bea, world.page_id)).items == []
        with pytest.raises(AuthorizationError):
            await _requests(world).approve(bea, world.page_id, asked.id)

    async def test_what_each_caller_sees_of_a_pages_requests(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        carl = await world.member(role="viewer", page=GrantLevel.READ)
        await SharingService(db).share(
            bea,
            await _page(world),
            resource_type=ARTIFACT,
            subject_user_id=carl.user_id,
            level=GrantLevel.EDIT,
        )

        mine = await _requests(world).list_requests(bea, world.page_id)
        theirs = await _requests(world).list_requests(carl, world.page_id)
        owners = await _requests(world).list_requests(world.olga, world.page_id)
        history = await _requests(world).list_requests(
            world.olga, world.page_id, pending_only=False
        )

        assert [(r.kind, r.can_decide) for r in mine.items] == [(ShareRequestKind.AUDIENCE, False)]
        assert theirs.items == []
        assert [r.can_decide for r in owners.items] == [True] and owners.total == 1
        assert history.total == 1

    async def test_with_no_owner_left_the_admins_decide_and_are_told(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        page = await _page(world)
        page.owner_user_id = None
        await db.flush()
        admin = await world.member(role="admin")
        carl = await world.member(role="viewer")

        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )

        told = await _told(db, page)
        assert admin.user_id in told and world.olga.user_id not in told
        assert carl.user_id not in told
        # Sharing a page that reads data needs the consent of an owner, and it has none.
        with pytest.raises(ConsentRequiredError):
            await _requests(world).approve(admin, world.page_id, asked.id)
        assert (await _pending(world, ShareRequestKind.ACCESS))[0].id == asked.id

    async def test_the_owner_sees_the_request_in_their_inbox_naming_page_and_person(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")
        await _requests(world).request_access(carl, world.page_id, ArtifactAccessRequestCreate())

        rows, _, _ = await NotificationCenterService(db).list_inbox(
            world.olga, after=None, limit=10
        )

        [row] = [r for r in rows if r.event_type == "artifact_share_requested"]
        assert "Pipeline" in row.summary and await _email(db, carl) in row.summary
        assert row.render_context["kind"] == "access"
        assert row.context_url == f"/artifacts/{world.page_id}?requests=open&org={world.org.id}"
        assert row.render_context["page_url"].endswith(row.context_url)


class TestWideningNeverConsents:
    """Sharing a page applies only on a consent that already holds for the version the
    audience is served; it never gives one, nor changes a version's state (#1974)."""

    async def test_a_declined_version_stays_declined_and_the_audience_keeps_its_own(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        reader = await world.member(role="viewer")
        ann = await world.member()
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        [request] = await _pending(world, ShareRequestKind.VERSION)
        await _requests(world).decline(world.olga, world.page_id, request.id)

        await SharingService(db).share(
            world.olga,
            await _page(world),
            resource_type=ARTIFACT,
            subject_user_id=ann.user_id,
            level=GrantLevel.READ,
        )

        assert (await world.version(2)).consent_state == "declined"
        assert await world.served(reader) == (1, "ok")

    async def test_a_pending_version_request_survives_an_unrelated_approval(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        bea = await world.member(page=GrantLevel.EDIT, reads_table=True)
        carl = await world.member(role="viewer")
        await world.publish("<p>v2</p>", fields=WIDER, by=bea)
        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )

        await _requests(world).approve(world.olga, world.page_id, asked.id)

        assert (await world.version(2)).consent_state == "pending"
        assert len(await _pending(world, ShareRequestKind.VERSION)) == 1
        assert await world.served(carl) == (1, "ok")

    @pytest.mark.security
    async def test_with_no_consent_that_holds_widening_is_refused_however_it_is_asked(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")
        asked = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate()
        )

        with pytest.raises(ConsentRequiredError) as refused:
            await _requests(world).approve(world.olga, world.page_id, asked.id)

        assert refused.value.status_code == 409
        assert (await world.version(1)).consent_state == "pending"
        assert (await _pending(world, ShareRequestKind.ACCESS))[0].id == asked.id

    @pytest.mark.security
    async def test_a_consent_withdrawn_since_no_longer_holds(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        await world.confirm(world.olga, 1)
        page = await _page(world)
        page.consent_withdrawn_at = datetime.now(UTC)
        await db.flush()

        with pytest.raises(ConsentRequiredError):
            await SharingService(db).set_visibility(
                world.olga, page, resource_type=ARTIFACT, visibility=Visibility.ORG
            )

    async def test_an_archived_page_is_neither_widened_nor_asked_about(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        bea = await _bound_and_shared(world)
        page = await _page(world)
        page.archived_at = datetime.now(UTC)
        await db.flush()
        ann = await world.member()

        with pytest.raises(ConflictError):
            await SharingService(db).share(
                world.olga,
                page,
                resource_type=ARTIFACT,
                subject_user_id=ann.user_id,
                level=GrantLevel.READ,
            )
        with pytest.raises(ConflictError):
            await file_access_request(db, bea, page, None)
        assert await _all(world, kind=ShareRequestKind.ACCESS) == []

    @pytest.mark.security
    async def test_whoever_asks_for_access_is_told_nothing_of_the_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.publish("<p>v1</p>")
        carl = await world.member(role="viewer")

        answer = await _requests(world).request_access(
            carl, world.page_id, ArtifactAccessRequestCreate(note="please")
        )

        assert isinstance(answer, ArtifactAccessRequested)
        assert set(answer.model_dump()) == {"id", "kind", "status", "created_at", "note"}
