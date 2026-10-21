"""Archiving a published page, and restoring it, against a real database.

An archived page keeps its versions, grants and name, and serves nothing: every
path that would show it - the console's view and data, a signed address minted
before the archive, the public link, the embed, the agent's own tools - answers
as it answers for a page that is not there. Archiving turns the public link off,
and restoring does not turn it back on.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.v1._sharing_loaders import load_artifact
from app.api.routes.v1.sharing import artifact_sharing_router
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo
from app.schemas.artifact import ArtifactPublicLinkUpdate, ArtifactUpdate
from app.services import artifact as artifacts
from app.services.access import ARTIFACT
from app.services.artifact import ArtifactService
from app.services.file_storage import LocalFileStorage
from app.services.sharing import SharingService
from tests.integration.virtual_table_support import ctx_for

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


async def _user(db: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    return user


async def _tenant(db: AsyncSession) -> tuple[Organization, User, Agent]:
    owner = await _user(db)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(organization)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role="member"))
    agent = Agent(
        organization_id=organization.id,
        name="Reporter",
        created_by_user_id=owner.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return organization, owner, agent


async def _member(db: AsyncSession, organization: Organization, role: str = "member") -> User:
    person = await _user(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return person


async def _publish(
    db: AsyncSession, organization: Organization, user: User, agent: Agent, body: str
) -> artifacts.PublishedArtifact:
    return await artifacts.publish_with(
        db,
        organization_id=organization.id,
        agent_id=agent.id,
        owner_user_id=user.id,
        run_id=None,
        name="weekly-report",
        title="Weekly report",
        media_type=ArtifactMediaType.HTML,
        data=body.encode(),
    )


async def _actions(db: AsyncSession, organization: Organization) -> list[str]:
    rows = await db.execute(
        select(AppAdminAuditLog.action)
        .where(AppAdminAuditLog.organization_id == organization.id)
        .order_by(AppAdminAuditLog.created_at)
    )
    return list(rows.scalars())


async def _org_wide_page(
    db: AsyncSession,
) -> tuple[Organization, User, Agent, artifacts.PublishedArtifact, AuthContext]:
    """A page the whole organization reads, with its public link on, and its owner's context."""
    organization, owner, agent = await _tenant(db)
    published = await _publish(db, organization, owner, agent, "<h1>v1</h1>")
    row = await db.get(Artifact, published.artifact_id)
    assert row is not None
    row.visibility = Visibility.ORG.value
    await db.flush()
    ctx = ctx_for(owner, organization, role="member")
    await ArtifactService(db).set_public_link(ctx, published.artifact_id)
    return organization, owner, agent, published, ctx


class TestArchiving:
    async def test_every_serving_path_refuses_an_archived_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent, published, ctx = await _org_wide_page(db)
        service = ArtifactService(db)
        page_id = published.artifact_id
        before = await service.view(ctx, page_id)
        token = before.url.rsplit("/", 1)[1]
        detail = await service.read(ctx, page_id)
        public_key = (detail.public_url or "").rsplit("/", 1)[1]
        reader = await _member(db, organization, role="viewer")
        reader_ctx = ctx_for(reader, organization, role="viewer")

        archived = await service.archive(ctx, page_id)

        assert archived.archived_at is not None
        assert archived.public_url is None
        assert archived.can_edit is True
        # A signed address minted before the archive serves nothing more.
        with pytest.raises(NotFoundError):
            await service.content(token)
        for refused in (
            service.view(ctx, page_id),
            service.data(ctx, page_id, published.version_id),
            service.versions(ctx, page_id),
            service.set_public_link(ctx, page_id),
            service.update(ctx, page_id, ArtifactUpdate(title="Renamed")),
            service.restore_version(ctx, page_id, published.version_id),
            service.update_public_link(ctx, page_id, ArtifactPublicLinkUpdate(embed_origins=[])),
            service.clear_public_link(ctx, page_id),
            service.public_view(public_key),
            service.read(reader_ctx, page_id),
        ):
            with pytest.raises(NotFoundError):
                await refused
        assert (await service.embed(public_key)).available is False
        # The editor reads it - the one who can restore it - and nothing else does.
        after = await service.read(ctx, page_id)
        assert (after.archived_at is not None, after.title) == (True, "Weekly report")
        assert await _actions(db, organization) == [
            "artifact.published",
            "artifact.public_link_enabled",
            "artifact.public_link_disabled",
            "artifact.archived",
        ]

    async def test_only_an_editor_still_reaches_an_archived_pages_sharing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """A reader is told the page is missing, as `GET /artifacts/{id}` tells them."""
        organization, _owner, _agent, published, ctx = await _org_wide_page(db)
        page_id = published.artifact_id
        reader = await _member(db, organization, role="viewer")
        reader_ctx = ctx_for(reader, organization, role="viewer")
        sharing = SharingService(db)
        get_sharing = next(
            route.endpoint
            for route in artifact_sharing_router.routes
            if isinstance(route, APIRoute) and route.path == "/{resource_id}/sharing"
        )
        assert (await get_sharing(page_id, db, sharing, reader_ctx)).resource_id == page_id

        await ArtifactService(db).archive(ctx, page_id)

        with pytest.raises(NotFoundError):
            await get_sharing(page_id, db, sharing, reader_ctx)
        with pytest.raises(NotFoundError):
            await load_artifact(db, page_id, reader_ctx)
        # The editor still manages who it is shared with while it is archived.
        assert (await get_sharing(page_id, db, sharing, ctx)).resource_id == page_id
        await sharing.share(
            ctx,
            await load_artifact(db, page_id, ctx),
            resource_type=ARTIFACT,
            subject_user_id=reader.id,
            level=GrantLevel.READ,
        )

    async def test_a_page_whose_key_survived_is_still_refused_by_the_public_link(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        _organization, _owner, _agent, published, ctx = await _org_wide_page(db)
        row = await db.get(Artifact, published.artifact_id)
        assert row is not None and row.public_key is not None
        key = row.public_key
        await ArtifactService(db).archive(ctx, published.artifact_id)
        row.public_key = key
        await db.flush()

        with pytest.raises(NotFoundError):
            await ArtifactService(db).public_view(key)

    async def test_archived_pages_are_listed_only_when_asked_for(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent, published, ctx = await _org_wide_page(db)
        service = ArtifactService(db)
        await service.archive(ctx, published.artifact_id)

        assert (await service.list_readable(ctx)).total == 0
        listed = await service.list_readable(ctx, include_archived=True)
        assert [item.id for item in listed.items] == [published.artifact_id]
        assert listed.items[0].archived_at is not None
        assert (await service.publishing_agents(ctx)).items == []

    async def test_archiving_twice_changes_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, _owner, _agent, published, ctx = await _org_wide_page(db)
        service = ArtifactService(db)
        first = await service.archive(ctx, published.artifact_id)

        second = await service.archive(ctx, published.artifact_id)

        assert second.archived_at == first.archived_at
        assert (await _actions(db, organization)).count("artifact.archived") == 1

    async def test_delete_still_reaches_an_archived_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        _organization, _owner, _agent, published, ctx = await _org_wide_page(db)
        service = ArtifactService(db)
        await service.archive(ctx, published.artifact_id)

        with patch("app.services.artifact.spawn_after_commit") as after_commit:
            await service.delete(ctx, published.artifact_id)
        after_commit.call_args.args[1].close()

        assert await db.get(Artifact, published.artifact_id) is None


class TestTheAgentAndAnArchivedPage:
    async def test_a_run_cannot_republish_read_preview_or_list_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent, published, ctx = await _org_wide_page(db)
        await ArtifactService(db).archive(ctx, published.artifact_id)

        with pytest.raises(AuthorizationError, match="is archived"):
            await _publish(db, organization, owner, agent, "<h1>v2</h1>")
        with pytest.raises(NotFoundError):
            await artifacts._open_current(
                db,
                organization_id=organization.id,
                agent_id=agent.id,
                reader_user_id=owner.id,
                run_id=None,
                name="weekly-report",
            )
        listing = await artifacts.list_for_run_with(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            reader_user_id=owner.id,
            editor_user_id=owner.id,
            run_id=None,
            room=False,
        )
        assert (listing.items, listing.total) == ([], 0)
        assert [
            version.number
            for version in await artifact_repo.list_versions(db, published.artifact_id)
        ] == [1]

    async def test_a_run_that_may_not_edit_it_hears_the_name_is_not_its_own(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """The archive is said only to a run that could have changed the page."""
        organization, _owner, agent, published, ctx = await _org_wide_page(db)
        await ArtifactService(db).archive(ctx, published.artifact_id)
        colleague = await _member(db, organization)

        with pytest.raises(AuthorizationError, match="different name") as refused:
            await _publish(db, organization, colleague, agent, "<h1>theirs</h1>")
        assert "archived" not in refused.value.message


class TestRestoring:
    async def test_a_restored_page_serves_again_with_its_public_link_still_off(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent, published, ctx = await _org_wide_page(db)
        service = ArtifactService(db)
        old_key = (await service.read(ctx, published.artifact_id)).public_url or ""
        await service.archive(ctx, published.artifact_id)

        restored = await service.unarchive(ctx, published.artifact_id)

        assert restored.archived_at is None
        assert restored.public_url is None
        view = await service.view(ctx, published.artifact_id)
        served = await service.content(view.url.rsplit("/", 1)[1])
        assert b"<h1>v1</h1>" in served.document
        with pytest.raises(NotFoundError):
            await service.public_view(old_key.rsplit("/", 1)[1])
        assert (await service.list_readable(ctx)).total == 1
        again = await _publish(db, organization, owner, agent, "<h1>v2</h1>")
        assert (again.artifact_id, again.version_number) == (published.artifact_id, 2)
        assert (await _actions(db, organization))[-2:] == [
            "artifact.unarchived",
            "artifact.published",
        ]

    async def test_a_page_that_is_not_archived_cannot_be_restored(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        _organization, _owner, _agent, published, ctx = await _org_wide_page(db)

        with pytest.raises(BadRequestError, match="not archived"):
            await ArtifactService(db).unarchive(ctx, published.artifact_id)


class TestWhoMayArchive:
    @pytest.mark.security
    async def test_a_reader_may_neither_archive_nor_restore(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, _owner, _agent, published, ctx = await _org_wide_page(db)
        colleague = ctx_for(await _member(db, organization), organization, role="member")
        service = ArtifactService(db)

        with pytest.raises(NotFoundError):
            await service.archive(colleague, published.artifact_id)
        await service.archive(ctx, published.artifact_id)
        with pytest.raises(NotFoundError):
            await service.unarchive(colleague, published.artifact_id)

    async def test_an_edit_grant_lets_a_colleague_archive_and_restore_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, _agent, published, _ctx = await _org_wide_page(db)
        colleague = await _member(db, organization, role="viewer")
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                resource_type="artifact",
                resource_id=published.artifact_id,
                subject_user_id=colleague.id,
                level=GrantLevel.EDIT.value,
                created_by_user_id=owner.id,
            )
        )
        await db.flush()
        service = ArtifactService(db)
        colleague_ctx = ctx_for(colleague, organization, role="viewer")

        assert (await service.archive(colleague_ctx, published.artifact_id)).archived_at is not None
        assert (await service.unarchive(colleague_ctx, published.artifact_id)).archived_at is None

    @pytest.mark.security
    async def test_another_organization_cannot_reach_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        _organization, _owner, _agent, published, _ctx = await _org_wide_page(db)
        other, stranger, _other_agent = await _tenant(db)
        outsider = ctx_for(stranger, other, role="owner")

        with pytest.raises(NotFoundError):
            await ArtifactService(db).archive(outsider, published.artifact_id)
        row = await db.get(Artifact, published.artifact_id)
        assert row is not None and row.archived_at is None
