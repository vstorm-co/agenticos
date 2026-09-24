"""What only a real database can prove about published artifacts (#70).

The identity is a unique constraint, the history is a row per version, the
listing scope is a query, and retention is a cascade plus a grant delete - each
is something a mocked session is happy to pretend it did. Storage is a real
local directory, so a version's bytes can be seen to land and to leave.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.db.models.agent import Agent
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo, retention_repo
from app.services import artifact as artifacts
from app.services.file_storage import LocalFileStorage
from app.services.retention import RetentionService

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
HTML = ArtifactMediaType.HTML


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
        stranger = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(stranger)
        await db.flush()
        theirs = await artifacts.publish_with(
            db,
            organization_id=organization.id,
            agent_id=agent.id,
            owner_user_id=stranger.id,
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
        stranger = uuid.uuid4()

        mine, _ = await artifact_repo.list_visible(
            db, organization_id=organization.id, user_id=user.id, see_all=False, shared_ids=[]
        )
        theirs, total = await artifact_repo.list_visible(
            db, organization_id=organization.id, user_id=stranger, see_all=False, shared_ids=[]
        )
        granted, _ = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=stranger,
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
