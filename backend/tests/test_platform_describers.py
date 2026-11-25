"""What the card of each described platform call says, read as the run's person."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.deps import AgentDeps
from app.agents.platform_describers import platform_describer
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.schemas.eval_run import EvalRunRequest

pytestmark = pytest.mark.anyio

ORG, PERSON, AGENT, SKILL, DATASET = (uuid.uuid4() for _ in range(5))
DEPS = AgentDeps(organization_id=ORG, run_person=PERSON)


@pytest.fixture(autouse=True)
def services(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def context() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    async def member(_db: object, organization_id: object, user_id: str | None) -> Any:
        if user_id is None:
            return None
        return AuthContext(user_id=uuid.UUID(user_id), organization_id=ORG, role="builder")

    monkeypatch.setattr("app.agents.platform_describers.get_db_context", context)
    monkeypatch.setattr("app.agents.platform_describers.acting_member", member)
    monkeypatch.setattr(
        "app.services.agent_registry.AgentRegistryService.get",
        AsyncMock(return_value=SimpleNamespace(id=AGENT, name="Support", organization_id=ORG)),
    )
    monkeypatch.setattr(
        "app.services.skills.SkillService.get",
        AsyncMock(return_value=SimpleNamespace(id=SKILL, name="Refunds")),
    )
    monkeypatch.setattr(
        "app.services.dataset.DatasetService.get",
        AsyncMock(return_value=SimpleNamespace(id=DATASET, name="Refund questions")),
    )
    monkeypatch.setattr(
        "app.repositories.agent.newest_version", AsyncMock(return_value=SimpleNamespace(version=6))
    )


async def _describe(tool: str, args: dict[str, Any], deps: AgentDeps = DEPS) -> Any:
    describe = platform_describer(tool)
    assert describe is not None
    return await describe(deps, args)


async def test_publishing_names_the_agent_and_the_version_it_makes() -> None:
    assert await _describe("agenticos_publish_agent", {"agent_id": str(AGENT)}) == {
        "agent": "Support",
        "version": "7",
    }


async def test_a_first_publish_makes_version_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.repositories.agent.newest_version", AsyncMock(return_value=None))
    described = await _describe("agenticos_publish_agent", {"agent_id": str(AGENT)})
    assert described == {"agent": "Support", "version": "1"}


@pytest.mark.parametrize(("version", "named"), [(4, "4"), (None, "")])
async def test_moving_a_skill_names_the_skill_the_agent_and_where_it_goes(
    version: int | None, named: str
) -> None:
    described = await _describe(
        "agenticos_change_skill_version",
        {"skill_id": str(SKILL), "agent_id": str(AGENT), "state": "pinned", "version": version},
    )
    assert described == {
        "skill": "Refunds",
        "agent": "Support",
        "state": "pinned",
        "version": named,
    }


async def test_accepting_a_skill_session_names_the_skill_and_the_outcome() -> None:
    described = await _describe(
        "agenticos_accept_skill_improvement", {"skill_id": str(SKILL), "outcome": "apply"}
    )
    assert described == {"skill": "Refunds", "outcome": "apply"}


@pytest.mark.parametrize("as_model", [False, True])
async def test_an_eval_names_the_agent_and_the_dataset_version_it_runs_on(as_model: bool) -> None:
    run = EvalRunRequest(dataset_id=DATASET, dataset_version=3)
    described = await _describe(
        "agenticos_start_eval_run",
        {"agent_id": str(AGENT), "run": run if as_model else run.model_dump(mode="json")},
    )
    assert described == {"agent": "Support", "dataset": "Refund questions", "version": "3"}


async def test_an_eval_on_the_latest_version_names_none() -> None:
    described = await _describe(
        "agenticos_start_eval_run", {"agent_id": str(AGENT), "run": {"dataset_id": str(DATASET)}}
    )
    assert described is not None and described["version"] == ""


@pytest.mark.parametrize(
    "tool", ["publish_agent", "agenticos_get_improvement", "github_agenticos_publish_agent"]
)
def test_only_a_described_platform_tool_has_a_describer(tool: str) -> None:
    assert platform_describer(tool) is None


@pytest.mark.security
async def test_a_record_the_person_cannot_read_or_a_malformed_call_describes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.agent_registry.AgentRegistryService.get",
        AsyncMock(side_effect=NotFoundError(message="Agent not found")),
    )
    assert await _describe("agenticos_publish_agent", {"agent_id": str(AGENT)}) is None
    assert await _describe("agenticos_publish_agent", {"agent_id": "not an id"}) is None
    assert await _describe("agenticos_publish_agent", {}) is None


@pytest.mark.security
async def test_a_run_with_no_person_describes_nothing() -> None:
    nobody = AgentDeps(organization_id=ORG, run_person=None)
    assert await _describe("agenticos_publish_agent", {"agent_id": str(AGENT)}, nobody) is None
