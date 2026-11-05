"""A profile credential never falls back to a tool key or shares an execution workspace."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import anyio
import anyio.lowlevel
import pytest
from pydantic import SecretStr
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import Workspace
from pydantic_ai.workspaces.local import LocalWorkspaceBackend

from app.agents.capabilities.coding_agent import _toolset
from app.agents.capabilities.coding_agent._harness import CodingReport, Harness
from app.agents.capabilities.coding_agent._personal import PersonalCodingTask
from app.agents.deps import AgentDeps
from app.clients.redis import RedisClient
from app.core.exceptions import ConflictError
from app.services.coding_account_lease import account_lease

pytestmark = pytest.mark.anyio
KEY = "my-private-credential"


class MemoryRedis(RedisClient):
    def __init__(self) -> None:
        super().__init__("redis://localhost")
        self.values: dict[str, str] = {}
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete_if_equal(self, key: str, value: str) -> bool:
        if self.values.get(key) != value:
            return False
        del self.values[key]
        return True


async def test_one_account_has_one_credential_writer_and_a_conflict_does_not_release_it() -> None:
    redis = MemoryRedis()
    async with account_lease("account", 60, redis=redis):
        held = redis.values["account"]
        with pytest.raises(ConflictError):
            async with account_lease("account", 60, redis=redis):
                pytest.fail("The account lease must be exclusive")
        assert redis.values["account"] == held
    assert not redis.values


async def test_cancelling_a_task_releases_its_account_lease() -> None:
    redis = MemoryRedis()
    with anyio.CancelScope() as scope:
        async with account_lease("account", 60, redis=redis):
            scope.cancel()
            await anyio.lowlevel.checkpoint()
    assert not redis.values


class PersonalExecutor:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.closed = False

    @asynccontextmanager
    async def session(
        self, ctx: RunContext[AgentDeps], *, harness: Harness, timeout_seconds: int
    ) -> AsyncGenerator[PersonalCodingTask]:
        try:
            yield PersonalCodingTask(
                workspace=self.workspace,
                account_id=uuid4(),
                label="My account",
                base_revision="a" * 64,
                result_archive=f"coding-results/{uuid4()}.zip",
                api_key=SecretStr(KEY),
                redactions=(SecretStr(KEY),),
            )
        finally:
            self.closed = True


async def test_profile_execution_uses_only_the_persons_key_and_private_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared, private = tmp_path / "shared", tmp_path / "private"
    shared.mkdir()
    private.mkdir()
    parent = Workspace(LocalWorkspaceBackend(shared))
    isolated = Workspace(LocalWorkspaceBackend(private))
    executor = PersonalExecutor(isolated)
    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="read_only",
        model=None,
        base_url="https://untrusted-gateway.invalid",
        api_key="the-tool-key-must-not-be-used",
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=executor,
    )

    def build_inner(**options: object) -> FunctionToolset[AgentDeps]:
        assert options["api_key"] == KEY
        assert options["base_url"] is None
        assert options["capture_changes"] is False
        toolset = FunctionToolset[AgentDeps]()

        async def run(ctx: RunContext[AgentDeps], task: str, fresh_session: bool = False) -> str:
            assert ctx.workspace is isolated and ctx.deps.subagent_events is None
            assert fresh_session
            await ctx.workspace.write_bytes("result.txt", b"private result")
            return CodingReport(
                harness="claude_code",
                access="read_only",
                outcome="completed",
                answer=f"Result {KEY}",
            ).model_dump_json()

        toolset.add_function(run, name="run_coding_agent")
        return toolset

    monkeypatch.setattr(_toolset, "build_coding_toolset", build_inner)
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4(), user_id=str(uuid4()), conversation_id=uuid4()),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Code",
        workspace=parent,
    )
    result = await outer.tools["run_coding_agent"].function(ctx, "Do the task")
    assert isinstance(result, str)
    report = CodingReport.model_validate_json(result)
    assert KEY not in result and report.account_label == "My account"
    assert report.execution == "isolated_task" and report.result_archive
    assert (private / "result.txt").exists() and not (shared / "result.txt").exists()
    assert executor.closed


async def test_owned_lease_connects_and_closes_its_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import coding_account_lease as module

    client = MemoryRedis()
    monkeypatch.setattr(module, "RedisClient", lambda _url: client)
    async with module.account_lease("owned", 5):
        assert client.connected
    assert not client.connected and not client.values


@pytest.mark.parametrize("task", ["", "Do work"])
async def test_personal_mode_without_initiating_authority_never_uses_the_tool_key(
    task: str,
) -> None:
    toolset = _toolset.build_coding_toolset(
        harness="claude_code",
        access="edit",
        model=None,
        base_url=None,
        api_key="team-key-is-not-a-fallback",
        timeout_seconds=60,
        runs_on="personal_sandbox",
    )
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4()), model=TestModel(), usage=RunUsage(), prompt="Task"
    )
    result = await toolset.tools["run_coding_agent"].function(ctx, task)
    assert "Scheduled jobs and channel publishers cannot borrow your account" in result
