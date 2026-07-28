"""Tests for the sharing service — changing who reaches a resource.

Sharing is an edit: only someone who can already change the resource may change
who else can. Every change is audited, which is what makes "who gave whom
access" answerable after the fact.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.access import COLLECTION
from app.services.sharing import SharingService


def _ctx(role: str, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=role,
    )


def _resource(org_id, owner_user_id=None, visibility=Visibility.PRIVATE):
    resource = MagicMock()
    resource.id = uuid.uuid4()
    resource.organization_id = org_id
    resource.owner_user_id = owner_user_id
    resource.visibility = visibility.value
    return resource


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


class TestGetSharing:
    @pytest.mark.anyio
    async def test_a_member_who_cannot_see_the_resource_is_told_it_does_not_exist(self):
        """Anything else turns the share list into a way to confirm ids exist.

        Refusing with "forbidden" would answer the only question the caller
        actually had, so the refusal has to look like an absence — and it must
        happen before the grant rows are read, not after.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with (
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.sharing.resource_grant_repo.list_for_resource", new=AsyncMock()
            ) as listed,
            pytest.raises(NotFoundError) as refused,
        ):
            await SharingService(_db()).get_sharing(ctx, resource, resource_type=COLLECTION)

        assert refused.value.details == {"resource_id": str(resource.id)}
        assert listed.await_count == 0

    @pytest.mark.anyio
    async def test_the_share_list_resolves_emails_only_inside_the_organization(self):
        """A grant stores a user id; the list shows an address, and the gap between
        them must not become a directory lookup. Resolving the id org-wide would
        let anyone who can see one shared resource read the email of a user who
        is not a member here.
        """
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)
        subject = uuid.uuid4()
        grant = MagicMock(subject_user_id=subject)

        with (
            patch(
                "app.services.sharing.resource_grant_repo.list_for_resource",
                new=AsyncMock(return_value=[grant]),
            ) as listed,
            patch(
                "app.services.sharing.member_repo.get_emails_for_users",
                new=AsyncMock(return_value={subject: "colleague@example.com"}),
            ) as emails,
        ):
            grants, resolved = await SharingService(_db()).get_sharing(
                ctx, resource, resource_type=COLLECTION
            )

        assert grants == [grant]
        assert resolved == {subject: "colleague@example.com"}
        assert listed.call_args.kwargs["organization_id"] == ctx.organization_id
        assert listed.call_args.kwargs["resource_type"] == COLLECTION.key
        assert listed.call_args.kwargs["resource_id"] == resource.id
        assert emails.call_args.kwargs["organization_id"] == ctx.organization_id
        assert emails.call_args.kwargs["user_ids"] == [subject]


class TestShare:
    @pytest.mark.anyio
    async def test_owner_can_share_and_the_change_is_audited(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)
        subject = uuid.uuid4()

        with (
            patch("app.services.sharing.member_repo.get", new=AsyncMock(return_value=MagicMock())),
            patch(
                "app.services.sharing.resource_grant_repo.upsert",
                new=AsyncMock(return_value=MagicMock()),
            ) as upsert,
            patch("app.services.sharing.record_audit", new=AsyncMock()) as audit,
        ):
            await SharingService(_db()).share(
                ctx,
                resource,
                resource_type=COLLECTION,
                subject_user_id=subject,
                level=GrantLevel.EDIT,
            )

        assert upsert.call_args.kwargs["subject_user_id"] == subject
        assert upsert.call_args.kwargs["level"] is GrantLevel.EDIT
        assert audit.call_args.kwargs["action"] == "resource.share"

    @pytest.mark.anyio
    async def test_member_cannot_share_someone_elses_resource(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with (
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(AuthorizationError),
        ):
            await SharingService(_db()).share(
                ctx,
                resource,
                resource_type=COLLECTION,
                subject_user_id=uuid.uuid4(),
                level=GrantLevel.READ,
            )

    @pytest.mark.anyio
    async def test_cannot_share_with_someone_outside_the_organization(self):
        """A grant pointing at a non-member would be a hole waiting to open."""
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with (
            patch("app.services.sharing.member_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(BadRequestError),
        ):
            await SharingService(_db()).share(
                ctx,
                resource,
                resource_type=COLLECTION,
                subject_user_id=uuid.uuid4(),
                level=GrantLevel.READ,
            )


class TestRevoke:
    @pytest.mark.anyio
    async def test_revoking_a_missing_share_is_not_found(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with (
            patch(
                "app.services.sharing.resource_grant_repo.revoke",
                new=AsyncMock(return_value=False),
            ),
            pytest.raises(NotFoundError),
        ):
            await SharingService(_db()).revoke(
                ctx, resource, resource_type=COLLECTION, subject_user_id=uuid.uuid4()
            )

    @pytest.mark.anyio
    async def test_revoke_is_audited(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with (
            patch(
                "app.services.sharing.resource_grant_repo.revoke",
                new=AsyncMock(return_value=True),
            ),
            patch("app.services.sharing.record_audit", new=AsyncMock()) as audit,
        ):
            await SharingService(_db()).revoke(
                ctx, resource, resource_type=COLLECTION, subject_user_id=uuid.uuid4()
            )

        assert audit.call_args.kwargs["action"] == "resource.unshare"


class TestVisibility:
    @pytest.mark.anyio
    async def test_visibility_change_records_both_ends(self):
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=ctx.user_id)

        with patch("app.services.sharing.record_audit", new=AsyncMock()) as audit:
            await SharingService(_db()).set_visibility(
                ctx, resource, resource_type=COLLECTION, visibility=Visibility.ORG
            )

        assert resource.visibility == Visibility.ORG.value
        assert audit.call_args.kwargs["details"] == {"from": "private", "to": "org"}

    @pytest.mark.anyio
    async def test_viewer_cannot_publish_a_resource_to_the_org(self):
        ctx = _ctx(OrgRoleName.VIEWER)
        resource = _resource(ctx.organization_id, owner_user_id=uuid.uuid4())

        with (
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(AuthorizationError),
        ):
            await SharingService(_db()).set_visibility(
                ctx, resource, resource_type=COLLECTION, visibility=Visibility.ORG
            )

    @pytest.mark.anyio
    async def test_making_an_unowned_resource_private_gives_it_an_owner(self):
        """Private to whom? An organization-wide vault secret has no owner, and
        an unowned private row is one nobody can see and nobody can delete —
        which the database refuses outright, arriving as a 500.

        The caller becomes the owner rather than being told to "transfer it
        first", because nothing in this product transfers ownership: that
        instruction has no way to be followed. It gives away nothing either —
        whoever gets here already passed the edit check, and editing a key
        includes rotating and deleting it."""
        ctx = _ctx(OrgRoleName.OWNER)
        resource = _resource(ctx.organization_id, owner_user_id=None, visibility=Visibility.ORG)

        with patch("app.services.sharing.record_audit", new=AsyncMock()) as audit:
            await SharingService(_db()).set_visibility(
                ctx, resource, resource_type=COLLECTION, visibility=Visibility.PRIVATE
            )

        assert resource.owner_user_id == ctx.user_id
        assert resource.visibility == Visibility.PRIVATE.value
        # Its own entry: "who owns this now" is not a question a visibility
        # change should answer quietly.
        assert [call.kwargs["action"] for call in audit.call_args_list] == [
            "resource.owner_claimed",
            "resource.visibility_changed",
        ]

    @pytest.mark.anyio
    async def test_an_owner_already_set_is_left_alone(self):
        """Going private must not quietly move somebody else's key to whoever
        happened to change its visibility."""
        ctx = _ctx(OrgRoleName.OWNER)
        owner = uuid.uuid4()
        resource = _resource(ctx.organization_id, owner_user_id=owner, visibility=Visibility.ORG)

        with patch("app.services.sharing.record_audit", new=AsyncMock()) as audit:
            await SharingService(_db()).set_visibility(
                ctx, resource, resource_type=COLLECTION, visibility=Visibility.PRIVATE
            )

        assert resource.owner_user_id == owner
        assert [call.kwargs["action"] for call in audit.call_args_list] == [
            "resource.visibility_changed"
        ]
