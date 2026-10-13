"""What only a real database can prove about the artifact changes of #1965-#1973.

The identity is now a unique index over an expression, the environment is read off
a run row, deleting an environment detaches rather than collides, a view counter is
an `UPDATE ... + 1`, pruning keeps a pinned version, and the agent filter is a join
through the listing's own visibility predicate. Each is something a mocked session
is happy to pretend it did.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.repositories import artifact_repo
from app.services import artifact as artifacts
from app.services.agent_environment import AgentEnvironmentService
from app.services.file_storage import LocalFileStorage

pytestmark = pytest.mark.anyio

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
    db.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRoleName.OWNER)
    )
    agent = Agent(
        organization_id=organization.id,
        name="Reporter",
        created_by_user_id=user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return organization, user, agent


async def _environment(
    db: AsyncSession, agent: Agent, name: str, *, is_default: bool = False
) -> AgentEnvironment:
    version = AgentVersion(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        version=int(uuid.uuid4().int % 1_000_000) + 1,
        spec={"name": agent.name},
    )
    db.add(version)
    await db.flush()
    environment = AgentEnvironment(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        name=name,
        version_id=version.id,
        is_default=is_default,
    )
    db.add(environment)
    await db.flush()
    return environment


async def _run(db: AsyncSession, agent: Agent, environment: AgentEnvironment | None) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.WEB.value,
        started_at=datetime.now(UTC),
        environment_id=environment.id if environment is not None else None,
    )
    db.add(run)
    await db.flush()
    return run


async def _publish(
    db: AsyncSession,
    organization: Organization,
    user: User,
    agent: Agent,
    *,
    body: str,
    run: AgentRun | None = None,
    name: str = "weekly-report",
    expected_version: int | None = None,
) -> artifacts.PublishedArtifact:
    return await artifacts.publish_with(
        db,
        organization_id=organization.id,
        agent_id=agent.id,
        owner_user_id=user.id,
        run_id=run.id if run is not None else None,
        name=name,
        title=None,
        media_type=HTML,
        data=body.encode(),
        expected_version=expected_version,
    )


class TestTheEnvironmentIsPartOfTheIdentity:
    async def test_a_staging_run_publishes_its_own_page_beside_the_default_one(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        staging = await _environment(db, agent, "staging")

        production = await _publish(db, organization, user, agent, body="<p>prod</p>")
        trial = await _publish(
            db, organization, user, agent, body="<p>try</p>", run=await _run(db, agent, staging)
        )
        again = await _publish(
            db, organization, user, agent, body="<p>try 2</p>", run=await _run(db, agent, staging)
        )

        assert trial.artifact_id != production.artifact_id
        assert again.artifact_id == trial.artifact_id
        assert again.version_number == 2
        prod_row = await db.get(Artifact, production.artifact_id)
        assert prod_row is not None
        assert prod_row.environment_id is None
        untouched = await artifact_repo.latest_version(db, production.artifact_id)
        assert untouched is not None
        assert untouched.number == 1

    async def test_a_run_that_named_the_default_environment_writes_the_default_page(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        default = await _environment(db, agent, "production", is_default=True)

        plain = await _publish(db, organization, user, agent, body="<p>a</p>")
        named = await _publish(
            db, organization, user, agent, body="<p>b</p>", run=await _run(db, agent, default)
        )

        assert named.artifact_id == plain.artifact_id

    @pytest.mark.security
    async def test_the_default_slot_holds_one_page_per_name(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        """The index reads a null environment as one value, which a plain unique
        constraint would not - it treats every null as distinct."""
        organization, user, agent = await _tenant(db)
        await _publish(db, organization, user, agent, body="<p>a</p>")

        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await artifact_repo.create(
                    db,
                    organization_id=organization.id,
                    owner_user_id=user.id,
                    agent_id=agent.id,
                    environment_id=None,
                    name="weekly-report",
                    title="Dup",
                )

    async def test_pages_with_no_publisher_left_may_share_a_name(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<p>a</p>")
        staging = await _environment(db, agent, "staging")
        second = await _publish(
            db, organization, user, agent, body="<p>b</p>", run=await _run(db, agent, staging)
        )

        await db.delete(agent)
        await db.flush()

        rows = (
            await db.execute(select(Artifact).where(Artifact.name == "weekly-report"))
        ).scalars()
        mine = {row.id: row for row in rows if row.organization_id == organization.id}
        assert set(mine) == {first.artifact_id, second.artifact_id}
        assert all(row.agent_id is None for row in mine.values())


class TestLookingAPageUp:
    async def test_a_name_is_found_in_its_environment_and_nowhere_else(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        staging = await _environment(db, agent, "staging")
        default_page = await _publish(db, organization, user, agent, body="<p>prod</p>")
        staging_page = await _publish(
            db, organization, user, agent, body="<p>try</p>", run=await _run(db, agent, staging)
        )

        async def _find(
            environment_id: uuid.UUID | None, name: str = "weekly-report"
        ) -> uuid.UUID | None:
            found = await artifact_repo.get_by_identity(
                db,
                organization_id=organization.id,
                agent_id=agent.id,
                environment_id=environment_id,
                name=name,
            )
            return found.id if found is not None else None

        assert await _find(None) == default_page.artifact_id
        assert await _find(staging.id) == staging_page.artifact_id
        assert await _find(None, "nothing-here") is None

        locked = await artifact_repo.lock(db, staging_page.artifact_id)
        assert locked is not None
        assert await artifact_repo.environment_names(db, [staging.id]) == {staging.id: "staging"}
        assert await artifact_repo.environment_names(db, []) == {}


class TestDeletingAnEnvironment:
    async def test_its_pages_stay_readable_and_never_land_in_the_default_slot(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        await _environment(db, agent, "production", is_default=True)
        staging = await _environment(db, agent, "staging")
        default_page = await _publish(db, organization, user, agent, body="<p>prod</p>")
        staging_page = await _publish(
            db, organization, user, agent, body="<p>try</p>", run=await _run(db, agent, staging)
        )
        ctx = AuthContext(user_id=user.id, organization_id=organization.id, role=OrgRoleName.OWNER)

        await AgentEnvironmentService(db).delete(ctx, agent.id, staging.id)

        detached = await db.get(Artifact, staging_page.artifact_id)
        assert detached is not None
        await db.refresh(detached)
        assert (detached.agent_id, detached.environment_id) == (None, None)
        kept = await db.get(Artifact, default_page.artifact_id)
        assert kept is not None
        assert kept.agent_id == agent.id


class TestEditsAgainstAVersion:
    async def test_an_edit_against_an_older_version_writes_nothing(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<p>1</p>")
        await _publish(db, organization, user, agent, body="<p>2</p>")

        with pytest.raises(ConcurrentChangeError):
            await _publish(db, organization, user, agent, body="<p>edit</p>", expected_version=1)

        current = await artifact_repo.latest_version(db, first.artifact_id)
        assert current is not None
        assert current.number == 2


class TestTheCounterAndThePin:
    async def test_every_opening_counts(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>a</p>")
        at = datetime(2026, 9, 30, 12, tzinfo=UTC)

        await artifact_repo.count_public_view(db, published.artifact_id, at=at)
        await artifact_repo.count_public_view(db, published.artifact_id, at=at)

        row = await db.get(Artifact, published.artifact_id)
        assert row is not None
        await db.refresh(row)
        assert (row.public_view_count, row.public_last_viewed_at) == (2, at)

    async def test_pruning_keeps_the_pinned_version_however_old(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        first = await _publish(db, organization, user, agent, body="<p>v1</p>")
        row = await db.get(Artifact, first.artifact_id)
        assert row is not None
        row.public_version_number = 1
        await db.flush()

        with patch.object(artifacts.settings, "ARTIFACT_MAX_VERSIONS", 2):
            for number in range(2, 6):
                await _publish(db, organization, user, agent, body=f"<p>v{number}</p>")

        kept = await db.execute(
            select(ArtifactVersion.number)
            .where(ArtifactVersion.artifact_id == first.artifact_id)
            .order_by(ArtifactVersion.number)
        )
        assert list(kept.scalars()) == [1, 4, 5]
        pinned = await artifact_repo.get_version_by_number(db, first.artifact_id, 1)
        assert pinned is not None
        assert pinned.id == first.version_id
        assert await artifact_repo.get_version_by_number(db, first.artifact_id, 2) is None

    @pytest.mark.security
    async def test_a_view_counter_below_zero_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        published = await _publish(db, organization, user, agent, body="<p>a</p>")
        row = await db.get(Artifact, published.artifact_id)
        assert row is not None
        row.public_view_count = -1
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.flush()


class TestTheAgentFilter:
    async def test_it_offers_only_the_publishers_of_pages_the_member_can_see(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        organization, user, agent = await _tenant(db)
        other = Agent(
            organization_id=organization.id,
            name="Secret agent",
            created_by_user_id=user.id,
            slug=f"s-{uuid.uuid4().hex[:8]}",
        )
        db.add(other)
        await db.flush()
        colleague = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(colleague)
        await db.flush()
        await _publish(db, organization, user, agent, body="<p>mine</p>")
        await artifacts.publish_with(
            db,
            organization_id=organization.id,
            agent_id=other.id,
            owner_user_id=colleague.id,
            run_id=None,
            name="private",
            title="Private",
            media_type=HTML,
            data=b"<p>theirs</p>",
        )

        agents = await artifact_repo.publishing_agents(
            db, organization_id=organization.id, user_id=user.id, see_all=False, shared_ids=[]
        )
        everyone = await artifact_repo.publishing_agents(
            db, organization_id=organization.id, user_id=user.id, see_all=True, shared_ids=[]
        )
        only_theirs, total = await artifact_repo.list_visible(
            db,
            organization_id=organization.id,
            user_id=user.id,
            see_all=True,
            shared_ids=[],
            agent_id=other.id,
        )

        assert agents == [(agent.id, "Reporter")]
        assert everyone == [(agent.id, "Reporter"), (other.id, "Secret agent")]
        assert (total, [row.name for row in only_theirs]) == (1, ["private"])
