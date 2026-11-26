"""What the card of each described platform call says, read as the run's person."""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.deps import AgentDeps
from app.agents.platform_describers import _READS, platform_describer
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


async def test_publishing_names_the_agent_and_no_version_a_later_publish_could_take() -> None:
    assert await _describe("agenticos_publish_agent", {"agent_id": str(AGENT)}) == {
        "agent": "Support"
    }


async def test_moving_a_skill_names_where_it_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    fork = uuid.uuid4()
    monkeypatch.setattr(
        "app.repositories.skill_version.get_fork",
        AsyncMock(return_value=SimpleNamespace(id=fork, name="Gentle tone")),
    )
    call = {"skill_id": str(SKILL), "agent_id": str(AGENT)}

    pinned = await _describe(
        "agenticos_change_skill_version", {**call, "state": "pinned", "version": 4}
    )
    forked = await _describe(
        "agenticos_change_skill_version", {**call, "state": "fork", "fork_id": str(fork)}
    )
    main = await _describe("agenticos_change_skill_version", {**call, "state": "main"})

    assert pinned == {"skill": "Refunds", "agent": "Support", "state": "pinned", "version": "4"}
    assert forked == {
        "skill": "Refunds",
        "agent": "Support",
        "state": "fork",
        "fork": "Gentle tone",
    }
    assert main == {"skill": "Refunds", "agent": "Support", "state": "main"}


@pytest.mark.security
async def test_a_fork_the_call_does_not_name_or_that_is_gone_describes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.repositories.skill_version.get_fork", AsyncMock(return_value=None))
    call = {"skill_id": str(SKILL), "agent_id": str(AGENT), "state": "fork"}

    assert await _describe("agenticos_change_skill_version", call) is None
    gone = {**call, "fork_id": str(uuid.uuid4())}
    assert await _describe("agenticos_change_skill_version", gone) is None


async def test_accepting_a_skill_session_names_the_skill_and_the_outcome() -> None:
    described = await _describe(
        "agenticos_accept_skill_improvement", {"skill_id": str(SKILL), "outcome": "apply"}
    )
    assert described == {"skill": "Refunds", "outcome": "apply"}


@pytest.mark.security
async def test_a_fork_for_chosen_agents_names_exactly_those_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    named = {AGENT: "Support", SKILL: "Billing"}
    monkeypatch.setattr(
        "app.services.agent_registry.AgentRegistryService.get",
        AsyncMock(side_effect=lambda _ctx, agent_id: SimpleNamespace(name=named[agent_id])),
    )
    call = {"skill_id": str(SKILL), "outcome": "fork_for_helped"}

    chosen = await _describe(
        "agenticos_accept_skill_improvement",
        {**call, "fork_agent_ids": [str(AGENT), str(SKILL)]},
    )
    helped = await _describe("agenticos_accept_skill_improvement", call)

    assert chosen == {
        "skill": "Refunds",
        "outcome": "fork_for_chosen",
        "agents": "Support, Billing",
    }
    assert helped == {"skill": "Refunds", "outcome": "fork_for_helped"}


def test_the_console_has_a_sentence_for_exactly_the_described_platform_tools() -> None:
    """The console's sentences are keyed by the platform tool's name, outside the
    capability catalog; a rename on either side must not leave a card silently plain."""
    captions = (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/agent-step-captions.ts"
    ).read_text()
    table = captions.split("PLATFORM_APPROVAL_SUMMARIES", 1)[1].split("};", 1)[0]
    named = set(re.findall(r"^\s*(agenticos_[a-z_]+):", table, re.MULTILINE))
    assert {name.removeprefix("agenticos_") for name in named} == set(_READS)
    assert all(platform_describer(name) is not None for name in named)


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
