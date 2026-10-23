"""What only a real database can prove about published artifacts (#70).

The identity is a unique constraint, the history is a row per version, the
listing scope is a query, and retention is a cascade plus a grant delete - each
is something a mocked session is happy to pretend it did. Storage is a real
local directory, so a version's bytes can be seen to land and to leave.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo, resource_grant_repo, retention_repo
from app.schemas.artifact import (
    ArtifactBinding,
    ArtifactConsentCreate,
    BindingDisclosure,
    BindingFilter,
    BindingRequest,
)
from app.schemas.table_view import TableViewCreate, TableViewRead
from app.schemas.virtual_table import ColumnInput, OptionInput, SchemaUpdate, TableRead
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService
from app.services.artifact_bindings import check_bindings, fingerprint
from app.services.file_storage import LocalFileStorage
from app.services.retention import RetentionService
from app.services.virtual_tables import TableViewService, VirtualTableService
from tests.integration.virtual_table_support import ctx_for, make_org, make_user, orders_table

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
HTML = ArtifactMediaType.HTML
MARKDOWN = ArtifactMediaType.MARKDOWN


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


async def _tenant(db: AsyncSession) -> tuple[Organization, User, Agent]:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    agent = await _agent(db, organization, user)
    return organization, user, agent


async def _agent(db: AsyncSession, organization: Organization, user: User) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        name="Reporter",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _publish(
    db: AsyncSession,
    organization: Organization,
    user: User,
    agent: Agent,
    *,
    body: str,
    name: str = "weekly-report",
    title: str = "Weekly report",
) -> artifacts.PublishedArtifact:
    return await artifacts.publish_with(
        db,
        organization_id=organization.id,
        agent_id=agent.id,
        owner_user_id=user.id,
        run_id=None,
        name=name,
        title=title,
        media_type=HTML,
        data=body.encode(),
    )


async def _versions(db: AsyncSession, artifact_id: uuid.UUID) -> list[int]:
    rows = await db.execute(
        select(ArtifactVersion.number)
        .where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(ArtifactVersion.number)
    )
    return list(rows.scalars())


class TestPublication:
    async def test_a_first_publication_is_a_private_artifact_owned_by_the_run_s_person(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)

        published = await _publish(db, organization, user, agent, body="<h1>v1</h1>")

        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None
        assert published.created is True
        assert published.version_number == 1
        assert artifact.visibility == Visibility.PRIVATE.value
        assert artifact.owner_user_id == user.id
        assert artifact.public_key is None
        version = await artifact_repo.latest_version(db, artifact.id)
        assert version is not None
        assert await storage.load(version.storage_path) == b"<h1>v1</h1>"

    async def test_a_version_keeps_the_bindings_it_was_published_with(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<h1>v1</h1>")
        table_id, title = str(uuid.uuid4()), str(uuid.uuid4())
        binding = {
            "name": "tickets",
            "table_id": table_id,
            "filters": [],
            "sort": {"by": "created_at", "direction": "asc"},
            "limit": 1000,
            "fields": {"title": title},
            "reach": {"tables": {table_id: {title: 0}}, "named_by": {}},
        }

        version = await artifact_repo.create_version(
            db,
            artifact_id=published.artifact_id,
            number=2,
            media_type=HTML.value,
            size_bytes=1,
            sha256="b" * 64,
            storage_path="artifacts/x/b.html",
            run_id=None,
            bindings=[binding],
        )
        await db.refresh(version)

        assert version.bindings[0]["name"] == "tickets"
        assert version.bindings == [binding]

    async def test_versions_published_before_bindings_read_as_empty(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<h1>v1</h1>")
        await db.execute(
            text(
                "INSERT INTO artifact_versions (id, artifact_id, number, media_type, "
                "size_bytes, sha256, storage_path) "
                "VALUES (:id, :artifact_id, 2, 'text/html', 1, :sha, 'artifacts/x/c.html')"
            ),
            {"id": uuid.uuid4(), "artifact_id": published.artifact_id, "sha": "c" * 64},
        )

        row = (
            await db.execute(
                select(ArtifactVersion).where(
                    ArtifactVersion.artifact_id == published.artifact_id,
                    ArtifactVersion.number == 2,
                )
            )
        ).scalar_one()

        assert row.bindings == []

    async def test_same_bytes_with_new_bindings_add_a_version(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish("<p>same</p>", run_person=world.owner.id)

        bound = await world.publish(
            "<p>same</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )
        again = await world.publish(
            "<p>same</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        assert (bound.unchanged, bound.version_number) == (False, 2)
        assert (again.unchanged, again.version_number) == (True, 2)
        assert await _versions(db, first.artifact_id) == [1, 2]

    async def test_republishing_the_name_updates_the_same_artifact(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<h1>v1</h1>")

        second = await _publish(
            db, organization, user, agent, body="<h1>v2</h1>", title="Weekly report 2"
        )

        assert second.artifact_id == first.artifact_id
        assert second.created is False
        assert second.version_number == 2
        assert second.title == "Weekly report 2"
        assert await _versions(db, first.artifact_id) == [1, 2]

    async def test_identical_bytes_add_no_version_but_take_the_new_title(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<h1>same</h1>")

        again = await _publish(db, organization, user, agent, body="<h1>same</h1>", title="Renamed")

        assert again.unchanged is True
        assert again.version_id == first.version_id
        assert again.title == "Renamed"
        assert await _versions(db, first.artifact_id) == [1]

    async def test_an_unchanged_publication_still_counts_as_one_for_retention(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """Retention measures age from `published_at`. A schedule that republishes
        identical numbers every day is keeping the page alive, and a sweep that
        read the date of the last *change* would delete it for being accurate."""
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<h1>same</h1>")
        stale = NOW - timedelta(days=120)
        await db.execute(
            text("UPDATE artifacts SET published_at = :at WHERE id = :id"),
            {"at": stale, "id": first.artifact_id},
        )
        artifact = await db.get(Artifact, first.artifact_id)
        assert artifact is not None
        await db.refresh(artifact)

        again = await _publish(db, organization, user, agent, body="<h1>same</h1>")

        await db.refresh(artifact)
        assert again.unchanged is True
        assert artifact.published_at > stale
        assert await _versions(db, first.artifact_id) == [1]

    async def test_the_same_name_under_another_agent_is_another_artifact(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        other = await _agent(db, organization, user)

        mine = await _publish(db, organization, user, agent, body="<p>a</p>")
        theirs = await _publish(db, organization, user, other, body="<p>a</p>")

        assert mine.artifact_id != theirs.artifact_id

    async def test_only_the_newest_versions_are_kept_and_their_bytes_after_the_commit(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        with (
            patch.object(artifacts.settings, "ARTIFACT_MAX_VERSIONS", 2),
            patch("app.services.artifact.spawn_after_commit") as after_commit,
        ):
            first = await _publish(db, organization, user, agent, body="<p>1</p>")
            first_path = (await artifact_repo.latest_version(db, first.artifact_id)).storage_path
            await _publish(db, organization, user, agent, body="<p>2</p>")
            await _publish(db, organization, user, agent, body="<p>3</p>")

        assert await _versions(db, first.artifact_id) == [2, 3]
        after_commit.assert_called_once()
        unlink = after_commit.call_args.args[1]
        await unlink
        assert not await storage.exists(first_path)

    async def test_a_pruned_version_sharing_bytes_with_a_kept_one_keeps_them(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """The path is the digest, so a page that went back to an earlier state
        shares its file with the version being pruned."""
        organization, user, agent = await _tenant(db)
        with (
            patch.object(artifacts.settings, "ARTIFACT_MAX_VERSIONS", 2),
            patch("app.services.artifact.spawn_after_commit") as after_commit,
        ):
            await _publish(db, organization, user, agent, body="<p>A</p>")
            await _publish(db, organization, user, agent, body="<p>B</p>")
            third = await _publish(db, organization, user, agent, body="<p>A</p>")

        assert await _versions(db, third.artifact_id) == [2, 3]
        after_commit.assert_not_called()


async def _member(db: AsyncSession, organization: Organization, role: str) -> User:
    person = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(person)
    await db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=person.id, role=role))
    await db.flush()
    return person


class TestWhoMayRepublish:
    """The name is shared by everyone who runs the agent; the page behind it is not."""

    @pytest.mark.security
    async def test_another_member_s_run_cannot_replace_the_owner_s_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        first = await _publish(db, organization, owner, agent, body="<p>mine</p>")
        colleague = await _member(db, organization, "member")

        with pytest.raises(AuthorizationError, match="different name"):
            await _publish(
                db, organization, colleague, agent, body="<p>theirs</p>", title="Hijacked"
            )

        artifact = await db.get(Artifact, first.artifact_id)
        assert artifact is not None
        assert artifact.title == "Weekly report"
        assert await _versions(db, first.artifact_id) == [1]

    @pytest.mark.security
    async def test_identical_bytes_are_refused_too_rather_than_retitling_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        first = await _publish(db, organization, owner, agent, body="<p>same</p>")
        colleague = await _member(db, organization, "member")

        with pytest.raises(AuthorizationError):
            await _publish(db, organization, colleague, agent, body="<p>same</p>", title="X")

        artifact = await db.get(Artifact, first.artifact_id)
        assert artifact is not None
        assert artifact.title == "Weekly report"

    async def test_an_edit_grant_lets_a_colleague_s_run_republish_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        first = await _publish(db, organization, owner, agent, body="<p>v1</p>")
        colleague = await _member(db, organization, "member")
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                resource_type="artifact",
                resource_id=first.artifact_id,
                subject_user_id=colleague.id,
                level=GrantLevel.EDIT.value,
                created_by_user_id=owner.id,
            )
        )
        await db.flush()

        second = await _publish(db, organization, colleague, agent, body="<p>v2</p>")

        assert second.artifact_id == first.artifact_id
        assert second.version_number == 2
        artifact = await db.get(Artifact, first.artifact_id)
        assert artifact is not None
        assert artifact.owner_user_id == owner.id

    async def test_a_role_that_edits_every_artifact_may_republish_any(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        first = await _publish(db, organization, owner, agent, body="<p>v1</p>")
        admin = await _member(db, organization, "admin")

        second = await _publish(db, organization, admin, agent, body="<p>v2</p>")

        assert (second.artifact_id, second.version_number) == (first.artifact_id, 2)

    @pytest.mark.security
    async def test_a_deactivated_admin_s_run_keeps_no_reach(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        await _publish(db, organization, owner, agent, body="<p>v1</p>")
        admin = await _member(db, organization, "admin")
        admin.is_active = False
        await db.flush()

        with pytest.raises(AuthorizationError):
            await _publish(db, organization, admin, agent, body="<p>v2</p>")

    @pytest.mark.security
    async def test_a_run_with_nobody_behind_it_reaches_only_an_ownerless_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        await _publish(db, organization, owner, agent, body="<p>v1</p>")

        async def headless(name: str, body: bytes) -> artifacts.PublishedArtifact:
            return await artifacts.publish_with(
                db,
                organization_id=organization.id,
                agent_id=agent.id,
                owner_user_id=None,
                run_id=None,
                name=name,
                title="Headless",
                media_type=HTML,
                data=body,
            )

        with pytest.raises(AuthorizationError):
            await headless("weekly-report", b"<p>v2</p>")
        made = await headless("ownerless", b"<p>a</p>")
        again = await headless("ownerless", b"<p>b</p>")
        assert (again.artifact_id, again.version_number) == (made.artifact_id, 2)


class TestConstraints:
    async def test_the_identity_is_unique_per_agent(self, db: AsyncSession) -> None:
        organization, user, agent = await _tenant(db)
        for _ in range(2):
            db.add(
                Artifact(
                    organization_id=organization.id,
                    agent_id=agent.id,
                    owner_user_id=user.id,
                    name="dup",
                    title="Dup",
                )
            )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_name_the_tool_would_refuse_is_refused_by_the_table_too(
        self, db: AsyncSession
    ) -> None:
        organization, user, agent = await _tenant(db)
        db.add(
            Artifact(
                organization_id=organization.id,
                agent_id=agent.id,
                owner_user_id=user.id,
                name="Weekly Report",
                title="t",
            )
        )
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_deleted_agent_leaves_its_artifacts_readable(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>x</p>")

        await db.execute(text("DELETE FROM agents WHERE id = :id"), {"id": agent.id})
        db.expire_all()

        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None
        assert artifact.agent_id is None

    async def test_deleting_the_organization_takes_its_artifacts(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        await _publish(db, organization, user, agent, body="<p>x</p>")

        await db.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": organization.id})

        assert await db.scalar(select(func.count()).select_from(ArtifactVersion)) == 0
        assert await db.scalar(select(func.count()).select_from(Artifact)) == 0


class TestReads:
    async def test_each_lookup_is_scoped_to_what_it_names(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        other, _, _ = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>x</p>")
        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None
        artifact.public_key = "k" * 32
        await db.flush()

        assert await artifact_repo.get(db, artifact.id, organization_id=organization.id) is artifact
        assert await artifact_repo.get(db, artifact.id, organization_id=other.id) is None
        assert await artifact_repo.get_by_public_key(db, "k" * 32) is artifact
        assert await artifact_repo.get_by_public_key(db, "nope") is None
        version = await artifact_repo.get_version(db, published.version_id)
        assert version is not None
        assert await artifact_repo.get_version(db, version.id, artifact_id=artifact.id) is version
        assert await artifact_repo.get_version(db, version.id, artifact_id=uuid.uuid4()) is None
        assert await artifact_repo.get_version_with_artifact(db, version.id) == (version, artifact)
        assert await artifact_repo.get_version_with_artifact(db, uuid.uuid4()) is None
        assert [v.number for v in await artifact_repo.list_versions(db, artifact.id)] == [1]
        assert "weekly-report" in repr(artifact)
        assert "number=1" in repr(version)

    async def test_deleting_an_artifact_takes_its_versions(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>x</p>")
        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None

        await artifact_repo.delete_artifact(db, artifact)
        await artifact_repo.delete_versions(db, [])

        assert await db.scalar(select(func.count()).select_from(ArtifactVersion)) == 0


class TestListing:
    async def test_shared_with_me_leaves_out_my_own_and_search_matches_the_title(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        mine = await _publish(db, organization, user, agent, body="<p>a</p>", name="mine")
        colleague = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(colleague)
        await db.flush()
        theirs = await artifacts.publish_with(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_user_id=colleague.id,
            run_id=None,
            name="theirs",
            title="Quarterly sales",
            media_type=HTML,
            data=b"<p>b</p>",
        )

        shared, _ = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=user.id,
            see_all=True,
            shared_ids=[mine.artifact_id, theirs.artifact_id],
            shared_with_me=True,
        )
        found, total = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=user.id,
            see_all=True,
            shared_ids=[],
            search="quarterly",
        )

        assert [item.id for item in shared] == [theirs.artifact_id]
        assert ([item.id for item in found], total) == ([theirs.artifact_id], 1)

    @pytest.mark.security
    async def test_a_private_artifact_is_listed_for_its_owner_alone(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>x</p>")
        colleague = uuid.uuid4()

        mine, _ = await artifact_repo.list_visible(
            db, organization_id=organization.id, user_id=user.id, see_all=False, shared_ids=[]
        )
        theirs, total = await artifact_repo.list_visible(
            db, organization_id=organization.id, user_id=colleague, see_all=False, shared_ids=[]
        )
        granted, _ = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=colleague,
            see_all=False,
            shared_ids=[published.artifact_id],
        )

        assert [item.id for item in mine] == [published.artifact_id]
        assert (theirs, total) == ([], 0)
        assert [item.id for item in granted] == [published.artifact_id]

    @pytest.mark.security
    async def test_another_organization_lists_nothing_even_with_everything_in_reach(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>x</p>")
        other, _, _ = await _tenant(db)

        items, total = await artifact_repo.list_visible(
            db,
            organization_id=other.id,
            user_id=user.id,
            see_all=True,
            shared_ids=[published.artifact_id],
        )

        assert (items, total) == ([], 0)

    async def test_the_current_version_of_each_is_one_query(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<p>1</p>", name="a")
        await _publish(db, organization, user, agent, body="<p>2</p>", name="a")
        second = await _publish(db, organization, user, agent, body="<p>1</p>", name="b")

        current = await artifact_repo.latest_versions(db, [first.artifact_id, second.artifact_id])

        assert current[first.artifact_id].number == 2
        assert current[second.artifact_id].number == 1
        assert await artifact_repo.latest_versions(db, []) == {}

    async def test_the_served_version_of_none_is_nothing_and_no_query(
        self, db: AsyncSession
    ) -> None:
        assert await artifact_repo.latest_served_versions(db, []) == {}


class TestRetention:
    async def test_an_artifact_nobody_republished_leaves_with_its_versions_bytes_and_grants(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        old = await _publish(db, organization, user, agent, body="<p>old</p>", name="old")
        recent = await _publish(db, organization, user, agent, body="<p>new</p>", name="new")
        old_path = (await artifact_repo.latest_version(db, old.artifact_id)).storage_path
        await db.execute(
            text("UPDATE artifacts SET published_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(days=120), "id": old.artifact_id},
        )
        await db.execute(
            text("UPDATE artifacts SET published_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(days=2), "id": recent.artifact_id},
        )
        db.add(
            ResourceGrant(
                organization_id=organization.id,
                resource_type="artifact",
                resource_id=old.artifact_id,
                subject_user_id=user.id,
                level=GrantLevel.READ.value,
                created_by_user_id=user.id,
            )
        )
        organization.retention_days = {"artifacts": 30}
        await db.flush()

        await RetentionService(db).sweep(now=NOW)

        remaining = (await db.execute(select(Artifact.id))).scalars().all()
        assert list(remaining) == [recent.artifact_id]
        assert not await storage.exists(old_path)
        grants = await db.scalar(
            select(func.count())
            .select_from(ResourceGrant)
            .where(ResourceGrant.resource_id == old.artifact_id)
        )
        assert grants == 0

    async def test_a_sweep_with_nothing_old_enough_removes_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        await _publish(db, organization, user, agent, body="<p>fresh</p>")
        organization.retention_days = {"artifacts": 365}
        await db.flush()

        results = await RetentionService(db).sweep(now=datetime.now(UTC))

        assert all("artifacts" not in result.removed for result in results)
        assert await db.scalar(select(func.count()).select_from(Artifact)) == 1

    async def test_the_rows_deleted_are_the_ones_whose_bytes_went(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """One locked set, not the cutoff asked twice. A publish landing between
        the unlink and the delete used to take the artifact out of the second
        question and leave it standing on files that were already gone."""
        organization, user, agent = await _tenant(db)
        old = await _publish(db, organization, user, agent, body="<p>old</p>")
        await db.execute(
            text("UPDATE artifacts SET published_at = :at WHERE id = :id"),
            {"at": NOW - timedelta(days=120), "id": old.artifact_id},
        )
        cutoff = NOW - timedelta(days=30)

        expiring = await retention_repo.lock_expiring_artifacts(
            db, organization_id=organization.id, cutoff=cutoff, limit=10
        )
        paths = await retention_repo.stored_paths_for_artifacts(db, artifact_ids=expiring)
        # The republish the old code raced: the row now reads as fresh.
        await db.execute(
            text("UPDATE artifacts SET published_at = :at WHERE id = :id"),
            {"at": NOW, "id": old.artifact_id},
        )
        removed = await retention_repo.delete_artifacts(
            db, organization_id=organization.id, artifact_ids=expiring
        )

        assert expiring == [old.artifact_id]
        assert len(paths) == 1
        assert removed == 1
        assert await db.get(Artifact, old.artifact_id) is None


LIVE_PAGE = "This page reads live data; only a run acting for a member can republish it."
READ = frozenset({"read"})


@dataclass
class _Bound:
    """An organization with a member, a table, a view of it and an agent to publish under."""

    db: AsyncSession
    organization: Organization
    owner: User
    ctx: AuthContext
    agent: Agent
    tables: VirtualTableService
    table: TableRead
    view: TableViewRead

    @property
    def grants(self) -> dict[uuid.UUID, frozenset[str]]:
        return {self.table.id: READ}

    def col(self, label: str) -> uuid.UUID:
        return next(c.id for c in self.table.columns if c.label == label)

    def ask(self, name: str = "tickets", **fields: str) -> dict[str, BindingRequest]:
        return {name: BindingRequest(view=self.view.id, fields=fields)}

    async def publish(
        self,
        body: str,
        *,
        run_person: uuid.UUID | None,
        bindings: dict[str, BindingRequest] | None = None,
        grants: dict[uuid.UUID, frozenset[str]] | None = None,
        media_type: ArtifactMediaType = HTML,
    ) -> artifacts.PublishedArtifact:
        return await artifacts.publish_with(
            self.db,
            organization_id=self.organization.id,
            agent_id=self.agent.id,
            owner_user_id=self.owner.id,
            run_id=None,
            name="live-report",
            title="Live report",
            media_type=media_type,
            data=body.encode(),
            bindings=bindings,
            run_person=run_person,
            table_grants=self.grants if grants is None else grants,
        )

    async def stored(self, artifact_id: uuid.UUID) -> list[dict[str, Any]]:
        latest = await artifact_repo.latest_version(self.db, artifact_id)
        assert latest is not None
        return latest.bindings

    async def archive(self, label: str) -> None:
        table = await self.tables.describe_table(self.ctx, self.table.id)
        await self.tables.update_schema(
            self.ctx,
            table.id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[
                    ColumnInput(
                        id=c.id,
                        label=c.label,
                        type=c.type,
                        options=[OptionInput(id=o.id, label=o.label) for o in c.options],
                    )
                    for c in table.columns
                    if c.label != label and not c.archived
                ],
            ),
        )


async def _bound(
    db: AsyncSession, *, visibility: Literal["private", "shared"] = "shared"
) -> _Bound:
    owner = await make_user(db)
    organization = await make_org(db, owner=owner)
    ctx = ctx_for(owner, organization)
    tables = VirtualTableService(db)
    table = await orders_table(tables, ctx)
    view = await TableViewService(db).create_view(
        ctx, table.id, TableViewCreate(name="Open", kind="table", visibility=visibility)
    )
    agent = await _agent(db, organization, owner)
    return _Bound(db, organization, owner, ctx, agent, tables, table, view)


class TestPublishingBindings:
    async def test_bindings_are_resolved_stored_and_disclosed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)

        published = await world.publish(
            "<p>live</p>", run_person=world.owner.id, bindings=world.ask(status="status")
        )

        disclosure = published.bindings["tickets"]
        assert isinstance(disclosure, BindingDisclosure)
        assert (disclosure.table, disclosure.fields) == (
            "Orders",
            {"status": "Status (single_select)"},
        )
        [stored] = await world.stored(published.artifact_id)
        status = world.col("Status")
        assert stored == {
            "name": "tickets",
            "table_id": str(world.table.id),
            "filters": [],
            "sort": {"by": "created_at", "direction": "asc"},
            "limit": 1000,
            "fields": {"status": str(status)},
            "reach": {"tables": {str(world.table.id): {str(status): 0}}, "named_by": {}},
        }

    async def test_the_audit_entry_carries_the_query_fingerprint(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)

        published = await world.publish(
            "<p>live</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        entry = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "artifact.published",
                    AppAdminAuditLog.target_id == str(published.artifact_id),
                )
            )
        ).scalar_one()
        stored = [
            ArtifactBinding.model_validate(b) for b in await world.stored(published.artifact_id)
        ]
        assert entry.details is not None
        assert entry.details["query_fingerprint"] == fingerprint(stored)

    async def test_omitted_bindings_carry_forward(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        second = await world.publish("<p>v2</p>", run_person=world.owner.id)

        assert second.version_number == 2
        assert second.bindings == {"tickets": "kept"}
        assert await world.stored(second.artifact_id) == await _stored_at(db, first)

    async def test_a_carried_binding_keeps_its_reach_after_the_table_moved_on(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """Carried as stored: the page reads nothing until the query is published again."""
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )
        await world.archive("Status")

        second = await world.publish("<p>v2</p>", run_person=world.owner.id)

        assert await world.stored(second.artifact_id) == await _stored_at(db, first)

    async def test_empty_bindings_clear_them(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        await world.publish(
            "<p>same</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        cleared = await world.publish("<p>same</p>", run_person=world.owner.id, bindings={})

        assert (cleared.unchanged, cleared.version_number) == (False, 2)
        assert cleared.bindings == {}
        assert await world.stored(cleared.artifact_id) == []

    async def test_a_markdown_republish_cannot_carry_html_bindings_forward(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        with pytest.raises(BadRequestError) as refused:
            await world.publish("# v2", run_person=world.owner.id, media_type=MARKDOWN)

        assert refused.value.message.startswith(
            "Bindings need an HTML page; a Markdown page runs no scripts."
        )
        assert "pass `bindings: {}` to drop them" in refused.value.message
        assert await _versions(db, first.artifact_id) == [1]

        # Doing what the refusal says publishes the Markdown page, unbound.
        dropped = await world.publish(
            "# v2", run_person=world.owner.id, media_type=MARKDOWN, bindings={}
        )
        assert dropped.bindings == {}
        assert await _versions(db, first.artifact_id) == [1, 2]

    async def test_a_markdown_page_with_new_bindings_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)

        with pytest.raises(BadRequestError, match="Bindings need an HTML page"):
            await world.publish(
                "# v1",
                run_person=world.owner.id,
                bindings=world.ask(status="Status"),
                media_type=MARKDOWN,
            )

    async def test_a_binding_problem_refuses_the_publish_and_is_said_once(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """Over the cap every binding reports the same problem; the model reads it once."""
        world = await _bound(db)
        many = {
            f"b{number}": BindingRequest(view=world.view.id, fields={"status": "Status"})
            for number in range(6)
        }

        with pytest.raises(BadRequestError) as refused:
            await world.publish("<p>v1</p>", run_person=world.owner.id, bindings=many)

        assert refused.value.message == "A page takes at most 5 bindings; this one has 6."

    @pytest.mark.security
    async def test_an_editor_cannot_bind_what_the_page_s_owner_cannot_read(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """The data is read with the owner's access, so an editor's run binds within it."""
        world = await _bound(db)
        first = await world.publish("<p>v1</p>", run_person=world.owner.id)
        page_owner = await _member(db, world.organization, "member")
        await _own(db, first.artifact_id, page_owner)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(
                "<p>v2</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
            )

        assert refused.value.message == (
            "Binding tickets: the page's owner can't read Orders, and a page's data is read "
            "with its owner's access."
        )
        assert await _versions(db, first.artifact_id) == [1]

    @pytest.mark.security
    async def test_a_publisher_who_cannot_read_the_table_binds_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        member = await _member(db, world.organization, "member")

        with pytest.raises(BadRequestError) as refused:
            await artifacts.publish_with(
                db,
                organization_id=world.organization.id,
                agent_id=world.agent.id,
                owner_user_id=member.id,
                run_id=None,
                name="theirs",
                title=None,
                media_type=HTML,
                data=b"<p>x</p>",
                bindings={
                    "tickets": BindingRequest(table=world.table.id, fields={"c": "Customer"})
                },
                run_person=member.id,
                table_grants=world.grants,
            )

        assert refused.value.message.startswith(f"Table {world.table.id} not found.")

    @pytest.mark.security
    async def test_new_bindings_on_a_widget_run_are_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)

        with pytest.raises(BadRequestError) as refused:
            await world.publish("<p>v1</p>", run_person=None, bindings=world.ask(status="Status"))

        assert refused.value.message == "Only a run acting for a member can bind a page to data."

    @pytest.mark.security
    async def test_a_widget_run_cannot_republish_a_bound_page_with_new_html(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        with pytest.raises(AuthorizationError) as refused:
            await world.publish("<script>steal()</script>", run_person=None)

        assert refused.value.message == LIVE_PAGE
        assert await _versions(db, first.artifact_id) == [1]

    @pytest.mark.security
    async def test_a_widget_run_cannot_clear_a_bound_page_s_bindings(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        with pytest.raises(AuthorizationError) as refused:
            await world.publish("<p>v1</p>", run_person=None, bindings={})

        assert refused.value.message == LIVE_PAGE
        assert await _versions(db, first.artifact_id) == [1]

    async def test_a_widget_run_refreshing_a_bound_page_unchanged_is_allowed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        again = await world.publish("<p>v1</p>", run_person=None)

        assert again.unchanged is True
        assert again.bindings == {"tickets": "kept"}
        assert await _versions(db, first.artifact_id) == [1]

    @pytest.mark.security
    async def test_a_run_person_who_left_counts_as_no_person(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )
        world.owner.is_active = False
        await db.flush()

        with pytest.raises(AuthorizationError) as refused:
            await world.publish("<p>v2</p>", run_person=world.owner.id)

        assert refused.value.message == LIVE_PAGE
        assert await _versions(db, first.artifact_id) == [1]

    @pytest.mark.security
    @pytest.mark.parametrize(
        "fields",
        [{"status": "Status"}, {"status": "Not a column"}],
        ids=["the-same-query", "labels-that-do-not-resolve"],
    )
    async def test_a_no_person_run_gets_one_refusal_whatever_its_bindings_resolve_to(
        self, db: AsyncSession, storage: LocalFileStorage, fields: dict[str, str]
    ) -> None:
        world = await _bound(db)
        await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )

        with (
            patch("app.services.artifact.check_bindings", wraps=check_bindings) as checked,
            pytest.raises(AuthorizationError) as refused,
        ):
            await world.publish("<p>v1</p>", run_person=None, bindings=world.ask(**fields))

        assert refused.value.message == LIVE_PAGE
        checked.assert_not_called()


async def _stored_at(db: AsyncSession, published: artifacts.PublishedArtifact) -> list[Any]:
    version = await db.get(ArtifactVersion, published.version_id)
    assert version is not None
    return version.bindings


async def _own(db: AsyncSession, artifact_id: uuid.UUID, owner: User) -> None:
    """Hand the page to `owner`, as an ownership switch would."""
    artifact = await db.get(Artifact, artifact_id)
    assert artifact is not None
    artifact.owner_user_id = owner.id
    await db.flush()


async def _two_versions(
    world: _Bound, bindings: dict[str, BindingRequest]
) -> tuple[artifacts.PublishedArtifact, artifacts.PublishedArtifact]:
    """A bound first version, then a second one with its bindings cleared."""
    first = await world.publish("<p>v1</p>", run_person=world.owner.id, bindings=bindings)
    second = await world.publish("<p>v2</p>", run_person=world.owner.id, bindings={})
    return first, second


class TestRestore:
    async def test_a_restored_version_names_the_one_it_came_from_and_a_publish_does_not(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first, _second = await _two_versions(world, {})

        detail = await ArtifactService(db).restore_version(
            world.ctx, first.artifact_id, first.version_id
        )
        await world.publish("<p>v4</p>", run_person=world.owner.id)

        assert detail.current_version is not None
        assert detail.current_version.restored_from == 1
        listed = await ArtifactService(db).versions(world.ctx, first.artifact_id)
        assert [(v.number, v.restored_from) for v in listed.items] == [
            (4, None),
            (3, 1),
            (2, None),
            (1, None),
        ]

    async def test_restore_keeps_the_queries_and_reads_their_reach_again(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        first, _second = await _two_versions(
            world, {**world.ask(status="Status"), **world.ask("totals", total="Total")}
        )
        before = await _stored_at(db, first)
        await world.archive("Total")

        detail = await ArtifactService(db).restore_version(
            world.ctx, first.artifact_id, first.version_id
        )

        assert detail.live is True
        assert [(b.name, b.fields) for b in detail.bindings] == [
            ("tickets", ["status"]),
            ("totals", ["total"]),
        ]
        stored = await world.stored(first.artifact_id)
        assert stored[0] == before[0]
        # Archiving bumped the column's revision; the page serves it nothing until republished.
        assert stored[1]["fields"] == before[1]["fields"]
        assert stored[1]["reach"] != before[1]["reach"]
        entry = (
            await db.execute(
                select(AppAdminAuditLog).where(
                    AppAdminAuditLog.action == "artifact.version_restored",
                    AppAdminAuditLog.target_id == str(first.artifact_id),
                )
            )
        ).scalar_one()
        assert entry.details == {"version": 3, "restored": 1, "bindings": ["tickets", "totals"]}

    async def test_restore_refuses_a_query_a_converted_column_no_longer_answers(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """`Total gt 5` on a number; `Total` turned to text, where `gt 5` means nothing."""
        world = await _bound(db)
        first, second = await _two_versions(
            world,
            {
                "big": BindingRequest(
                    table=world.table.id,
                    fields={"customer": "Customer"},
                    filters=[BindingFilter(column="Total", op="gt", value=5)],
                )
            },
        )
        table = await world.tables.describe_table(world.ctx, world.table.id)
        await world.tables.update_schema(
            world.ctx,
            table.id,
            SchemaUpdate(
                expected_version=table.schema_version,
                columns=[
                    ColumnInput(
                        id=c.id,
                        label=c.label,
                        type="text" if c.label == "Total" else c.type,
                        options=[OptionInput(id=o.id, label=o.label) for o in c.options],
                    )
                    for c in table.columns
                    if not c.archived
                ],
            ),
        )

        with pytest.raises(BadRequestError) as refused:
            await ArtifactService(db).restore_version(
                world.ctx, first.artifact_id, first.version_id
            )

        assert refused.value.message.startswith("Binding big: filter 1: ")
        assert refused.value.message.endswith("So this version can't be restored.")
        latest = await artifact_repo.latest_version(db, first.artifact_id)
        assert latest is not None and latest.id == second.version_id

    @pytest.mark.security
    async def test_restore_checks_as_the_restorer(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """An editor of the page who cannot read the table cannot put its data back."""
        world = await _bound(db)
        first, second = await _two_versions(world, world.ask(status="Status"))
        editor = await _member(db, world.organization, "member")
        await resource_grant_repo.upsert(
            db,
            organization_id=world.organization.id,
            subject_user_id=editor.id,
            resource_type="artifact",
            resource_id=first.artifact_id,
            level=GrantLevel.EDIT,
        )

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(
                ctx_for(editor, world.organization, "member"), first.artifact_id, first.version_id
            )

        assert refused.value.message == (
            "Binding tickets reads a table you can't read. So this version can't be restored."
        )
        latest = await artifact_repo.latest_version(db, first.artifact_id)
        assert latest is not None and latest.id == second.version_id

    @pytest.mark.security
    async def test_the_detail_shows_bindings_only_to_an_editor(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _bound(db)
        published = await world.publish(
            "<p>v1</p>", run_person=world.owner.id, bindings=world.ask(status="Status")
        )
        reader = await _member(db, world.organization, "member")
        await resource_grant_repo.upsert(
            db,
            organization_id=world.organization.id,
            subject_user_id=reader.id,
            resource_type="artifact",
            resource_id=published.artifact_id,
            level=GrantLevel.READ,
        )
        service = ArtifactService(db)
        # An audience is served only a version its owner confirmed (or one reading no data).
        as_owner = await service.read(world.ctx, published.artifact_id)
        latest = await artifact_repo.latest_version(db, published.artifact_id)
        assert latest is not None and latest.query_fingerprint is not None
        await service.confirm_data(
            world.ctx,
            published.artifact_id,
            latest.id,
            ArtifactConsentCreate(fingerprint=latest.query_fingerprint),
        )

        as_reader = await service.read(
            ctx_for(reader, world.organization, "member"), published.artifact_id
        )

        assert (as_reader.can_edit, as_reader.live, as_reader.bindings) == (False, True, [])
        assert [(b.name, b.table_id, b.fields) for b in as_owner.bindings] == [
            ("tickets", world.table.id, ["status"])
        ]


class TestFollowing:
    """A follower hears about a new version through the inbox (#1977)."""

    async def _notices(self, db: AsyncSession, user_id: uuid.UUID) -> list[Notification]:
        rows = await db.execute(
            select(Notification).where(
                Notification.recipient_user_id == user_id,
                Notification.event_type == NotificationEventType.ARTIFACT_VERSION_PUBLISHED.value,
            )
        )
        return list(rows.scalars())

    async def test_a_new_version_reaches_followers_who_can_read_it_and_nobody_else(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        published = await _publish(db, organization, owner, agent, body="<h1>v1</h1>")
        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None
        artifact.visibility = Visibility.ORG.value
        reader = await _member(db, organization, OrgRoleName.MEMBER)
        await artifact_repo.follow(db, artifact_id=artifact.id, user_id=reader.id)
        await artifact_repo.follow(db, artifact_id=artifact.id, user_id=reader.id)
        await artifact_repo.follow(db, artifact_id=artifact.id, user_id=owner.id)
        # Following is a subscription, not a grant: a page made private again
        # stops reaching the follower without the follow being undone.
        colleague = await _member(db, organization, OrgRoleName.MEMBER)
        await artifact_repo.follow(db, artifact_id=artifact.id, user_id=colleague.id)

        await _publish(db, organization, owner, agent, body="<h1>v2</h1>")
        await _publish(db, organization, owner, agent, body="<h1>v2</h1>")

        assert await artifact_repo.is_following(db, artifact_id=artifact.id, user_id=reader.id)
        [notice] = await self._notices(db, reader.id)
        assert notice.occurrence_id == f"{artifact.id}:2"
        assert notice.organization_id == organization.id
        assert await self._notices(db, owner.id) == []

        artifact.visibility = Visibility.PRIVATE.value
        await _publish(db, organization, owner, agent, body="<h1>v3</h1>")

        assert [row.occurrence_id for row in await self._notices(db, colleague.id)] == [
            f"{artifact.id}:2"
        ]
        assert len(await self._notices(db, reader.id)) == 1

    async def test_unfollowing_stops_the_notices(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, owner, agent = await _tenant(db)
        published = await _publish(db, organization, owner, agent, body="<h1>v1</h1>")
        artifact = await db.get(Artifact, published.artifact_id)
        assert artifact is not None
        artifact.visibility = Visibility.ORG.value
        reader = await _member(db, organization, OrgRoleName.MEMBER)
        await artifact_repo.follow(db, artifact_id=artifact.id, user_id=reader.id)
        await artifact_repo.unfollow(db, artifact_id=artifact.id, user_id=reader.id)

        await _publish(db, organization, owner, agent, body="<h1>v2</h1>")

        assert await self._notices(db, reader.id) == []
        assert not await artifact_repo.is_following(db, artifact_id=artifact.id, user_id=reader.id)


class TestAProjectsApps:
    """`project_id` narrows the listing to the apps a run in the project's chats wrote."""

    async def test_only_apps_a_run_in_the_project_published_are_listed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        from app.db.models.agent_run import AgentRun, RunStatus
        from app.db.models.conversation import Conversation
        from app.db.models.project import Project

        organization, user, agent = await _tenant(db)
        project = Project(organization_id=organization.id, owner_user_id=user.id, name="Treasury")
        db.add(project)
        await db.flush()
        inside = Conversation(
            organization_id=organization.id, user_id=user.id, project_id=project.id
        )
        outside = Conversation(organization_id=organization.id, user_id=user.id)
        db.add_all([inside, outside])
        await db.flush()
        runs = {}
        for name, conversation in (("in", inside), ("out", outside)):
            run = AgentRun(
                organization_id=organization.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                status=RunStatus.COMPLETED.value,
            )
            db.add(run)
            await db.flush()
            runs[name] = run
        made_here = await artifacts.publish_with(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_user_id=user.id,
            run_id=runs["in"].id,
            name="cash-report",
            title="Cash report",
            media_type=HTML,
            data=b"<p>cash</p>",
        )
        await artifacts.publish_with(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_user_id=user.id,
            run_id=runs["out"].id,
            name="elsewhere",
            title="Elsewhere",
            media_type=HTML,
            data=b"<p>else</p>",
        )

        items, total = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=user.id,
            see_all=True,
            shared_ids=[],
            project_id=project.id,
        )

        assert total == 1
        assert [item.id for item in items] == [made_here.artifact_id]
