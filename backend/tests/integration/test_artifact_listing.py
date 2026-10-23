"""`list_artifacts` against a real database: what a run's reader may see of its agent's pages.

The predicate is SQL, and every refusal in it is one a mocked session would
happily pretend to apply: another member's private page, another agent's and
another environment's pages, another organization's, anything but an
organization-wide page read into a group chat - by `list_artifacts` or
`preview_artifact` - and a reader who has left.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.artifact import ArtifactMediaType
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import artifact_repo
from app.services import artifact as artifacts
from app.services.file_storage import LocalFileStorage

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


async def _person(db: AsyncSession, organization: Organization | None, role: str) -> User:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    if organization is not None:
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=role))
        await db.flush()
    return user


async def _organization(db: AsyncSession) -> tuple[Organization, User, Agent]:
    founder = await _person(db, None, OrgRoleName.OWNER)
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=founder.id
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=organization.id, user_id=founder.id, role=OrgRoleName.OWNER
        )
    )
    agent = await _agent(db, organization, founder)
    return organization, founder, agent


async def _agent(db: AsyncSession, organization: Organization, creator: User) -> Agent:
    agent = Agent(
        organization_id=organization.id,
        name="Reporter",
        created_by_user_id=creator.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _staging_run(db: AsyncSession, agent: Agent) -> AgentRun:
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
        name=f"staging-{uuid.uuid4().hex[:6]}",
        version_id=version.id,
        is_default=False,
    )
    db.add(environment)
    await db.flush()
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        status=RunStatus.COMPLETED.value,
        surface=RunSurface.WEB.value,
        started_at=datetime.now(UTC),
        environment_id=environment.id,
    )
    db.add(run)
    await db.flush()
    return run


async def _page(
    db: AsyncSession,
    agent: Agent,
    owner: User | None,
    name: str,
    *,
    visibility: Visibility = Visibility.PRIVATE,
    run: AgentRun | None = None,
) -> uuid.UUID:
    published = await artifacts.publish_with(
        db,
        organization_id=agent.organization_id,
        agent_id=agent.id,
        owner_user_id=owner.id if owner is not None else None,
        run_id=run.id if run is not None else None,
        name=name,
        title=name.title(),
        media_type=ArtifactMediaType.HTML,
        data=f"<p>{name}</p>".encode(),
    )
    if visibility is not Visibility.PRIVATE:
        found = await artifact_repo.get(
            db, published.artifact_id, organization_id=agent.organization_id
        )
        assert found is not None
        await artifact_repo.update(db, artifact=found, update_data={"visibility": visibility})
    return published.artifact_id


async def _grant(
    db: AsyncSession, artifact_id: uuid.UUID, to: User, level: GrantLevel, by: User, org: uuid.UUID
) -> None:
    db.add(
        ResourceGrant(
            organization_id=org,
            resource_type="artifact",
            resource_id=artifact_id,
            subject_user_id=to.id,
            level=level.value,
            created_by_user_id=by.id,
        )
    )
    await db.flush()


class _World:
    """Two members of one organization, their agent's pages, and pages they must never see."""

    organization: Organization
    agent: Agent
    ada: User
    bo: User
    admin: User
    shared: uuid.UUID


async def _world(db: AsyncSession) -> _World:
    world = _World()
    world.organization, _, world.agent = await _organization(db)
    world.ada = await _person(db, world.organization, OrgRoleName.MEMBER)
    world.bo = await _person(db, world.organization, OrgRoleName.MEMBER)
    world.admin = await _person(db, world.organization, OrgRoleName.ADMIN)
    agent = world.agent
    await _page(db, agent, world.ada, "ada-private")
    await _page(db, agent, world.ada, "ada-org", visibility=Visibility.ORG)
    world.shared = await _page(db, agent, world.ada, "ada-shared")
    await _grant(db, world.shared, world.bo, GrantLevel.READ, world.ada, world.organization.id)
    await _page(db, agent, world.bo, "bo-private")
    # Never in this agent's listing, whoever reads it.
    other_agent = await _agent(db, world.organization, world.ada)
    await _page(db, other_agent, world.ada, "other-agent", visibility=Visibility.ORG)
    await _page(
        db,
        agent,
        world.ada,
        "staging-page",
        run=await _staging_run(db, agent),
        visibility=Visibility.ORG,
    )
    _, stranger_owner, stranger_agent = await _organization(db)
    await _page(db, stranger_agent, stranger_owner, "elsewhere", visibility=Visibility.ORG)
    return world


async def _listed(
    db: AsyncSession,
    world: _World,
    reader: User,
    *,
    editor: User | None = None,
    room: bool = False,
    run: AgentRun | None = None,
    limit: int = artifacts.LIST_LIMIT,
) -> artifacts.ArtifactListing:
    return await artifacts.list_for_run_with(
        db,
        organization_id=world.organization.id,
        agent_id=world.agent.id,
        reader_user_id=reader.id,
        editor_user_id=(editor or reader).id,
        run_id=run.id if run is not None else None,
        room=room,
        limit=limit,
    )


def _names(listing: artifacts.ArtifactListing) -> set[str]:
    return {item.name for item in listing.items}


@pytest.mark.security
class TestWhatAReaderSees:
    async def test_a_member_sees_their_own_the_organization_s_and_what_was_shared(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.bo)
        assert _names(listing) == {"bo-private", "ada-org", "ada-shared"}
        assert listing.total == 3

    async def test_a_role_that_reaches_every_page_sees_every_page_of_this_agent_here(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.admin)
        assert _names(listing) == {"ada-private", "ada-org", "ada-shared", "bo-private"}

    async def test_a_named_environment_lists_its_own_pages_only(self, db: AsyncSession) -> None:
        world = await _world(db)
        run = await _staging_run(db, world.agent)
        staged = await _page(db, world.agent, world.ada, "staged", run=run)
        listing = await _listed(db, world, world.ada, run=run)
        assert _names(listing) == {"staged"}
        assert staged

    async def test_a_group_chat_lists_only_what_the_whole_organization_may_see(
        self, db: AsyncSession
    ) -> None:
        """Not the speaker's private or team pages, nor one shared with them alone."""
        world = await _world(db)
        await _page(db, world.agent, world.bo, "bo-team", visibility=Visibility.TEAM)
        assert _names(await _listed(db, world, world.bo)) == {
            "bo-private",
            "bo-team",
            "ada-org",
            "ada-shared",
        }
        assert _names(await _listed(db, world, world.bo, room=True)) == {"ada-org"}
        assert _names(await _listed(db, world, world.admin, room=True)) == {"ada-org"}

    async def test_a_reader_who_left_keeps_only_their_own_pages(self, db: AsyncSession) -> None:
        world = await _world(db)
        await db.execute(
            delete(OrganizationMember).where(OrganizationMember.user_id == world.ada.id)
        )
        await db.flush()
        assert _names(await _listed(db, world, world.ada)) == {
            "ada-private",
            "ada-org",
            "ada-shared",
        }
        assert _names(await _listed(db, world, world.ada, room=True)) == {"ada-org"}

    async def test_the_listing_stops_at_its_limit_and_says_how_many_there_are(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.admin, limit=2)
        assert len(listing.items) == 2
        assert listing.total == 4


@asynccontextmanager
async def _session(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    yield db


async def _previewed(
    db: AsyncSession, world: _World, reader: User, name: str, *, room: bool
) -> artifacts.ArtifactPreview:
    with patch("app.services.artifact.get_db_context", side_effect=lambda: _session(db)):
        return await artifacts.preview_source(
            organization_id=world.organization.id,
            agent_id=world.agent.id,
            reader_user_id=reader.id,
            run_id=None,
            name=name,
            room=room,
            has_person=True,
        )


@pytest.mark.security
class TestWhatAPreviewOpens:
    """`preview_artifact` opens what `list_artifacts` lists, for the same audience."""

    async def test_alone_the_reader_previews_their_own_and_what_was_shared_with_them(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        for name in ("bo-private", "ada-org", "ada-shared"):
            assert (await _previewed(db, world, world.bo, name, room=False)).name == name

    async def test_a_group_chat_previews_an_organization_wide_page(self, db: AsyncSession) -> None:
        world = await _world(db)
        assert (await _previewed(db, world, world.bo, "ada-org", room=True)).name == "ada-org"

    @pytest.mark.parametrize("name", ["bo-private", "bo-team", "ada-shared"])
    async def test_a_group_chat_never_previews_a_page_only_the_speaker_reaches(
        self, db: AsyncSession, name: str
    ) -> None:
        world = await _world(db)
        await _page(db, world.agent, world.bo, "bo-team", visibility=Visibility.TEAM)
        with pytest.raises(NotFoundError):
            await _previewed(db, world, world.bo, name, room=True)

    async def test_a_role_that_reaches_every_page_does_not_widen_a_group_chat(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        with pytest.raises(NotFoundError):
            await _previewed(db, world, world.admin, "ada-private", room=True)


@pytest.mark.security
class TestWhatAReadOpens:
    """`read_artifact` reads out a page's source - a static page's records among it."""

    async def _read(
        self, db: AsyncSession, world: _World, reader: User, name: str, *, room: bool
    ) -> artifacts.ArtifactSource:
        with patch("app.services.artifact.get_db_context", side_effect=lambda: _session(db)):
            return await artifacts.read_source(
                organization_id=world.organization.id,
                agent_id=world.agent.id,
                reader_user_id=reader.id,
                run_id=None,
                name=name,
                room=room,
            )

    async def test_alone_the_reader_reads_what_was_shared_with_them(self, db: AsyncSession):
        world = await _world(db)
        assert (await self._read(db, world, world.bo, "ada-shared", room=False)).name == (
            "ada-shared"
        )

    @pytest.mark.parametrize("name", ["bo-private", "bo-team", "ada-shared"])
    async def test_a_group_chat_never_reads_a_page_only_the_speaker_reaches(
        self, db: AsyncSession, name: str
    ):
        world = await _world(db)
        await _page(db, world.agent, world.bo, "bo-team", visibility=Visibility.TEAM)
        with pytest.raises(NotFoundError):
            await self._read(db, world, world.bo, name, room=True)

    async def test_a_group_chat_reads_an_organization_wide_page(self, db: AsyncSession):
        world = await _world(db)
        assert (await self._read(db, world, world.bo, "ada-org", room=True)).name == "ada-org"


class TestWhatARunMayRepublish:
    async def test_may_edit_is_the_rule_a_publish_is_held_to(self, db: AsyncSession) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.bo)
        may = {item.name: item.may_edit for item in listing.items}
        assert may == {"bo-private": True, "ada-org": False, "ada-shared": False}

    async def test_an_edit_grant_makes_a_shared_page_republishable(self, db: AsyncSession) -> None:
        world = await _world(db)
        await db.execute(
            update(ResourceGrant)
            .where(ResourceGrant.resource_id == world.shared)
            .values(level=GrantLevel.EDIT.value)
        )
        await db.flush()
        listing = await _listed(db, world, world.bo)
        assert {item.name for item in listing.items if item.may_edit} == {
            "bo-private",
            "ada-shared",
        }

    async def test_a_publisher_standing_in_answers_may_edit_not_the_reader(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.bo, editor=world.admin)
        assert all(item.may_edit for item in listing.items)

    async def test_a_run_for_nobody_may_republish_only_a_page_nobody_owns(
        self, db: AsyncSession
    ) -> None:
        world = await _world(db)
        await _page(db, world.agent, None, "nobodys", visibility=Visibility.ORG)
        listing = await artifacts.list_for_run_with(
            db,
            organization_id=world.organization.id,
            agent_id=world.agent.id,
            reader_user_id=world.bo.id,
            editor_user_id=None,
            run_id=None,
            room=False,
        )
        assert {item.name for item in listing.items if item.may_edit} == {"nobodys"}

    async def test_a_row_carries_what_the_model_is_told(self, db: AsyncSession) -> None:
        world = await _world(db)
        listing = await _listed(db, world, world.ada)
        (row,) = [item for item in listing.items if item.name == "ada-shared"]
        assert (row.title, row.version_number, row.media_type) == (
            "Ada-Shared",
            1,
            ArtifactMediaType.HTML,
        )
        assert (row.bindings, row.visibility, row.public) == ([], "private", False)
        assert row.console_path == f"/artifacts/{world.shared}?org={world.organization.id}"
