"""Skill versions and forks, through the app.

What a version holds, how lines are numbered and who may change them is
`integration/test_skill_versions`'s, against a real database. Here the service is a
stub, and what is left is the HTTP contract the skill page is built on: each path
reaches the right method with what was sent, answers with the right status, and a
refusal keeps its status on the way out.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.exceptions import BadRequestError, ConcurrentChangeError, InUseError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.skill_version import SkillVersionSource
from app.main import app
from app.schemas.skill_merge import MergeTextRead, SkillMergeRead
from app.schemas.skill_version import (
    BehindMainList,
    ReturnedToMain,
    SkillAgentList,
    SkillBindingChanged,
    SkillForkList,
    SkillForkRead,
    SkillVersionList,
    SkillVersionRead,
    VersionNumberRef,
    VersionResourceRead,
)

pytestmark = pytest.mark.anyio

SKILL = uuid.uuid4()
VERSION = uuid.uuid4()
FORK = uuid.uuid4()
RUN = uuid.uuid4()
MERGE = f"/api/v1/skills/{SKILL}/improvements/{RUN}/merge"
NOW = datetime(2026, 11, 2, tzinfo=UTC)


def _version(fork_id: uuid.UUID | None = None) -> SkillVersionRead:
    return SkillVersionRead(
        id=VERSION,
        skill_id=SKILL,
        fork_id=fork_id,
        number=2,
        source=SkillVersionSource.EDIT,
        previous=None,
        created_at=NOW,
        agents=0,
        description="How refunds work.",
        content="Ask for the receipt.",
        resources=[],
    )


def _fork() -> SkillForkRead:
    return SkillForkRead(
        id=FORK,
        skill_id=SKILL,
        name="returns",
        base=VersionNumberRef(id=VERSION, number=2),
        started_from=VersionNumberRef(id=VERSION, number=2),
        latest=None,
        changes=0,
        behind_main=0,
        agents=0,
        archive_candidate=False,
        created_at=NOW,
    )


@pytest.fixture
def service() -> MagicMock:
    stub = MagicMock()
    stub.list_versions = AsyncMock(return_value=SkillVersionList(items=[_version()], total=1))
    stub.read_version = AsyncMock(return_value=_version())
    stub.read_resource = AsyncMock(
        return_value=VersionResourceRead(name="refs/a.md", description=None, content="one")
    )
    stub.edit = AsyncMock(return_value=_version(FORK))
    stub.restore = AsyncMock(return_value=_version())
    stub.list_forks = AsyncMock(return_value=SkillForkList(items=[_fork()], total=1))
    stub.create_fork = AsyncMock(return_value=_fork())
    stub.rename_fork = AsyncMock(return_value=_fork())
    stub.archive_fork = AsyncMock(return_value=_fork())
    return stub


@pytest.fixture
def ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


@pytest.fixture
async def client(
    service: MagicMock, ctx: AuthContext, mock_redis: MagicMock
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_redis] = lambda: mock_redis
    app.dependency_overrides[deps.get_skill_version_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as opened:
        yield opened
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _clean_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


async def test_history_lists_one_line_and_pages(client, service, ctx):
    response = await client.get(
        f"/api/v1/skills/{SKILL}/versions", params={"fork_id": str(FORK), "skip": 5, "limit": 10}
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    service.list_versions.assert_awaited_once_with(ctx, SKILL, fork_id=FORK, skip=5, limit=10)


async def test_history_without_a_fork_is_mains(client, service, ctx):
    await client.get(f"/api/v1/skills/{SKILL}/versions")

    service.list_versions.assert_awaited_once_with(ctx, SKILL, fork_id=None, skip=0, limit=50)


async def test_a_page_larger_than_a_hundred_is_refused(client, service):
    response = await client.get(f"/api/v1/skills/{SKILL}/versions", params={"limit": 101})

    assert response.status_code == 422
    service.list_versions.assert_not_awaited()


async def test_a_version_is_read_with_its_text(client, service, ctx):
    response = await client.get(f"/api/v1/skills/{SKILL}/versions/{VERSION}")

    assert response.status_code == 200
    assert response.json()["content"] == "Ask for the receipt."
    service.read_version.assert_awaited_once_with(ctx, SKILL, VERSION)


async def test_a_versions_file_is_read_by_its_path(client, service, ctx):
    response = await client.get(f"/api/v1/skills/{SKILL}/versions/{VERSION}/resources/refs/a.md")

    assert response.status_code == 200
    assert response.json()["content"] == "one"
    service.read_resource.assert_awaited_once_with(ctx, SKILL, VERSION, "refs/a.md")


async def test_an_edit_is_saved_as_a_new_version(client, service):
    body = {
        "fork_id": str(FORK),
        "base_version_id": str(VERSION),
        "description": "How refunds work.",
        "content": "Ask for the receipt.",
    }

    response = await client.post(f"/api/v1/skills/{SKILL}/versions", json=body)

    assert response.status_code == 201
    [_, skill_id, data] = service.edit.await_args.args
    assert (skill_id, data.fork_id, data.base_version_id) == (SKILL, FORK, VERSION)


async def test_an_edit_without_the_version_it_was_made_on_is_refused(client, service):
    response = await client.post(
        f"/api/v1/skills/{SKILL}/versions", json={"description": "d", "content": "c"}
    )

    assert response.status_code == 422
    service.edit.assert_not_awaited()


async def test_an_edit_on_a_line_that_moved_is_a_conflict(client, service):
    service.edit.side_effect = ConcurrentChangeError(message="newer", details={})

    response = await client.post(
        f"/api/v1/skills/{SKILL}/versions",
        json={"base_version_id": str(VERSION), "description": "d", "content": "c"},
    )

    assert response.status_code == 409


async def test_restore_answers_with_the_new_version(client, service):
    response = await client.post(
        f"/api/v1/skills/{SKILL}/versions/{VERSION}/restore",
        json={"base_version_id": str(VERSION)},
    )

    assert response.status_code == 201
    [_, skill_id, version_id, data] = service.restore.await_args.args
    assert (skill_id, version_id, data.base_version_id) == (SKILL, VERSION, VERSION)


async def test_a_version_the_caller_cannot_reach_is_not_found(client, service):
    service.read_version.side_effect = NotFoundError(message="Version not found", details={})

    response = await client.get(f"/api/v1/skills/{SKILL}/versions/{VERSION}")

    assert response.status_code == 404


async def test_forks_are_listed_active_by_default(client, service):
    response = await client.get(f"/api/v1/skills/{SKILL}/forks")
    archived = await client.get(f"/api/v1/skills/{SKILL}/forks", params={"archived": "true"})

    assert response.status_code == archived.status_code == 200
    assert [call.kwargs["archived"] for call in service.list_forks.await_args_list] == [False, True]


async def test_a_fork_is_created_from_a_version(client, service):
    response = await client.post(
        f"/api/v1/skills/{SKILL}/forks",
        json={"name": "returns", "from_version_id": str(VERSION)},
    )

    assert response.status_code == 201
    [_, skill_id, data] = service.create_fork.await_args.args
    assert (skill_id, data.name, data.from_version_id) == (SKILL, "returns", VERSION)


async def test_a_fork_needs_a_name(client, service):
    response = await client.post(
        f"/api/v1/skills/{SKILL}/forks", json={"name": "", "from_version_id": str(VERSION)}
    )

    assert response.status_code == 422
    service.create_fork.assert_not_awaited()


async def test_a_fork_is_renamed(client, service):
    response = await client.patch(f"/api/v1/skills/{SKILL}/forks/{FORK}", json={"name": "eu"})

    assert response.status_code == 200
    [_, skill_id, fork_id, data] = service.rename_fork.await_args.args
    assert (skill_id, fork_id, data.name) == (SKILL, FORK, "eu")


async def test_a_fork_is_archived(client, service, ctx):
    response = await client.post(f"/api/v1/skills/{SKILL}/forks/{FORK}/archive")

    assert response.status_code == 200
    service.archive_fork.assert_awaited_once_with(ctx, SKILL, FORK)


async def test_a_used_skill_answers_its_deletion_as_in_use(client):
    """The refusal keeps its status and names who uses it, so the page can say so."""
    skills = MagicMock()
    skills.delete = AsyncMock(
        side_effect=InUseError(message="in use", details={"agents": [], "hidden": 2})
    )
    app.dependency_overrides[deps.get_skill_service] = lambda: skills

    response = await client.delete(f"/api/v1/skills/{SKILL}")

    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"agents": [], "hidden": 2}


@pytest.mark.parametrize(("query", "remove"), [("", False), ("?remove_from_agents=true", True)])
async def test_removing_from_agents_is_asked_for_by_name(client, ctx, query, remove):
    skills = MagicMock()
    skills.delete = AsyncMock(return_value=None)
    app.dependency_overrides[deps.get_skill_service] = lambda: skills

    response = await client.delete(f"/api/v1/skills/{SKILL}{query}")

    assert response.status_code == 204
    skills.delete.assert_awaited_once_with(ctx, SKILL, remove_from_agents=remove)


async def test_a_skills_agents_are_listed(client, ctx):
    agents = MagicMock()
    agents.agents = AsyncMock(
        return_value=SkillAgentList(
            main_latest=VersionNumberRef(id=VERSION, number=2), items=[], hidden=3
        )
    )
    app.dependency_overrides[deps.get_skill_agent_service] = lambda: agents

    response = await client.get(f"/api/v1/skills/{SKILL}/agents")

    assert response.status_code == 200
    assert response.json()["hidden"] == 3
    agents.agents.assert_awaited_once_with(ctx, SKILL)


async def test_an_agent_is_moved_to_a_fork(client, ctx):
    agent_id = uuid.uuid4()
    agents = MagicMock()
    agents.change_binding = AsyncMock(return_value=SkillBindingChanged(published=False))
    app.dependency_overrides[deps.get_skill_agent_service] = lambda: agents

    response = await client.put(
        f"/api/v1/skills/{SKILL}/agents/{agent_id}/binding",
        json={"state": "fork", "fork_id": str(FORK)},
    )

    assert response.status_code == 200
    assert response.json()["published"] is False
    [_, skill_id, moved, data] = agents.change_binding.await_args.args
    assert (skill_id, moved, data.state, data.fork_id) == (SKILL, agent_id, "fork", FORK)


@pytest.mark.parametrize(
    "body",
    [
        {"state": "pinned"},
        {"state": "fork", "version": 2},
        {"state": "main", "version": 2},
    ],
)
async def test_a_move_names_exactly_what_its_state_needs(client, body):
    agents = MagicMock()
    agents.change_binding = AsyncMock()
    app.dependency_overrides[deps.get_skill_agent_service] = lambda: agents

    response = await client.put(f"/api/v1/skills/{SKILL}/agents/{uuid.uuid4()}/binding", json=body)

    assert response.status_code == 422
    agents.change_binding.assert_not_awaited()


async def test_what_main_left_behind_is_listed_for_the_organization(client, ctx):
    """Not read as a skill id: the path is declared before `/{skill_id}`."""
    catch_up = MagicMock()
    catch_up.behind_main = AsyncMock(return_value=BehindMainList(items=[], total=0, hidden=2))
    app.dependency_overrides[deps.get_skill_catch_up_service] = lambda: catch_up

    response = await client.get("/api/v1/skills/behind-main")

    assert response.status_code == 200
    assert response.json()["hidden"] == 2
    catch_up.behind_main.assert_awaited_once_with(ctx)


async def test_a_forks_agents_are_returned_to_main_by_the_ones_asked_for(client, ctx):
    agent_id = uuid.uuid4()
    catch_up = MagicMock()
    catch_up.return_to_main = AsyncMock(
        return_value=ReturnedToMain(agents=[], hidden=0, remaining=0, archived=True)
    )
    app.dependency_overrides[deps.get_skill_catch_up_service] = lambda: catch_up

    response = await client.post(
        f"/api/v1/skills/{SKILL}/forks/{FORK}/return-to-main",
        json={"agent_ids": [str(agent_id)]},
    )

    assert response.status_code == 200
    assert response.json()["archived"] is True
    [_, skill_id, fork_id, data] = catch_up.return_to_main.await_args.args
    assert (skill_id, fork_id, data.agent_ids) == (SKILL, FORK, [agent_id])


def _merge() -> SkillMergeRead:
    text = MergeTextRead(
        state="conflict", base="b", fork="f", main="m", result=None, proposed=None, edited=False
    )
    ref = VersionNumberRef(id=VERSION, number=2)
    return SkillMergeRead(
        id=uuid.uuid4(),
        run_id=RUN,
        skill_id=SKILL,
        fork_id=FORK,
        kind="catch_up",
        base=ref,
        fork=ref,
        main=ref,
        description=text,
        parts=[text],
        files=[],
        conflicts=2,
        unresolved=2,
    )


@pytest.fixture
def merges() -> MagicMock:
    stub = MagicMock()
    for method in ("read_merge", "edit_description", "edit_part", "pick_file"):
        setattr(stub, method, AsyncMock(return_value=_merge()))
    app.dependency_overrides[deps.get_skill_catch_up_service] = lambda: stub
    return stub


async def test_a_sessions_merge_is_read_and_each_edit_reaches_its_call(client, ctx, merges):
    read = await client.get(MERGE)
    described = await client.patch(f"{MERGE}/description", json={"result": "Refunds."})
    parted = await client.patch(f"{MERGE}/parts/3", json={"result": "both"})
    picked = await client.patch(f"{MERGE}/files", json={"name": "a.md", "take": "fork"})

    assert [response.status_code for response in (read, described, parted, picked)] == [200] * 4
    assert read.json()["unresolved"] == 2
    merges.read_merge.assert_awaited_once_with(ctx, SKILL, RUN)
    [_, _, _, description] = merges.edit_description.await_args.args
    [_, _, _, index, part] = merges.edit_part.await_args.args
    [_, _, _, pick] = merges.pick_file.await_args.args
    assert (description.result, index, part.result) == ("Refunds.", 3, "both")
    assert (pick.name, pick.take) == ("a.md", "fork")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("description", {"result": ""}),
        ("description", {"result": "x" * 501}),
        ("files", {"name": "a.md", "take": "base"}),
        ("parts/first", {"result": "both"}),
    ],
)
async def test_an_edit_the_merge_cannot_take_is_refused_before_the_service(
    client, merges, path, body
):
    response = await client.patch(f"{MERGE}/{path}", json=body)

    assert response.status_code == 422
    merges.edit_description.assert_not_awaited()
    merges.edit_part.assert_not_awaited()
    merges.pick_file.assert_not_awaited()


@pytest.mark.parametrize(
    ("refusal", "status"),
    [
        (NotFoundError(message="This session merges nothing"), 404),
        (BadRequestError(message="A merge is edited only while its session waits at Changes"), 400),
    ],
)
async def test_a_merge_refusal_keeps_its_status(client, merges, refusal, status):
    merges.edit_part = AsyncMock(side_effect=refusal)

    response = await client.patch(f"{MERGE}/parts/0", json={"result": "both"})

    assert response.status_code == status
