"""A profile credential never falls back to a tool key or shares an execution workspace."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
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
from app.agents.capabilities.coding_agent._personal import PersonalCodingTask, SignIn
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
    def __init__(self, workspace: Workspace, sign_in: SignIn | None = None) -> None:
        self.workspace = workspace
        self.sign_in = sign_in
        self.closed = False
        self.harnesses: list[Harness] = []

    @asynccontextmanager
    async def session(
        self,
        ctx: RunContext[AgentDeps],
        *,
        harness: Harness,
        timeout_seconds: int,
        session: str = "main",
    ) -> AsyncGenerator[PersonalCodingTask]:
        self.harnesses.append(harness)
        try:
            yield PersonalCodingTask(
                workspace=self.workspace,
                account_id=uuid4(),
                label="My account",
                base_revision="a" * 64,
                result_archive=f"coding-results/{uuid4()}.zip",
                api_key=None if self.sign_in else SecretStr(KEY),
                sign_in=self.sign_in,
                redactions=(SecretStr(KEY),),
            )
        finally:
            self.closed = True


@pytest.mark.security
@pytest.mark.parametrize(
    "outcome",
    [
        "structured",
        "edited",
        "unstructured",
        "non-text",
        "refused",
        "subscription",
        "unstructured_read",
    ],
)
async def test_profile_execution_uses_only_the_persons_key_and_private_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    shared, private = tmp_path / "shared", tmp_path / "private"
    shared.mkdir()
    private.mkdir()
    parent = Workspace(LocalWorkspaceBackend(shared))
    isolated = Workspace(LocalWorkspaceBackend(private))
    from tests.test_coding_agent import SIGNED_IN, _Store

    executor = PersonalExecutor(
        isolated, (lambda _org: _Store()) if outcome == "subscription" else None
    )
    editable = outcome in {"edited", "unstructured"}
    discard = AsyncMock()
    if editable:
        from app.agents.capabilities.coding_agent import _changes

        monkeypatch.setattr(
            _changes, "begin", AsyncMock(return_value=_changes.Baseline("snapshot", "tree"))
        )
        monkeypatch.setattr(_changes, "finish", AsyncMock(return_value=None))
        monkeypatch.setattr(_changes, "discard", discard)
    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="edit" if editable else "read_only",
        model=None,
        base_url="https://untrusted-gateway.invalid",
        api_key="the-tool-key-must-not-be-used",
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=executor,
    )

    def build_inner(**options: object) -> FunctionToolset[AgentDeps]:
        assert options["api_key"] == (None if outcome == "subscription" else KEY)
        assert options["base_url"] is None
        assert options["capture_changes"] is False
        toolset = FunctionToolset[AgentDeps]()

        async def run(
            ctx: RunContext[AgentDeps],
            task: str,
            fresh_session: bool = False,
            session: str = "main",
        ) -> str | dict[str, str]:
            assert ctx.workspace is isolated and ctx.deps.subagent_events is None
            assert not fresh_session and session == "main"
            await ctx.workspace.write_bytes("result.txt", b"private result")
            if outcome == "non-text":
                return {"invalid": "result"}
            if outcome == "refused":
                from app.core.exceptions import BadRequestError

                raise BadRequestError(message="Budget refused")
            if outcome in {"unstructured", "unstructured_read"}:
                return f"Unstructured result {KEY}"
            return CodingReport(
                harness="claude_code",
                access="read_only",
                outcome="completed",
                answer=f"Result {KEY} {SIGNED_IN.access_token} {SIGNED_IN.refresh_token}"
                if outcome == "subscription"
                else f"Result {KEY}",
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
    if outcome == "non-text":
        with pytest.raises(TypeError, match="non-text"):
            await outer.tools["run_coding_agent"].function(ctx, "Do the task")
        assert executor.closed
        return
    result = await outer.tools["run_coding_agent"].function(ctx, "Do the task")
    assert isinstance(result, str)
    if outcome in {"unstructured", "unstructured_read", "refused"}:
        assert KEY not in result and executor.closed
        if editable:
            discard.assert_awaited()
        return
    report = CodingReport.model_validate_json(result)
    assert KEY not in result and report.account_label == "My account"
    assert report.execution == "isolated_task" and report.result_archive
    assert (private / "result.txt").exists() and not (shared / "result.txt").exists()
    assert executor.closed
    if outcome == "subscription":
        assert SIGNED_IN.access_token not in result and SIGNED_IN.refresh_token not in result
    if editable:
        discard.assert_awaited_once()


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


async def test_personal_coding_requires_a_nonempty_task_before_opening_the_account(
    tmp_path: Path,
) -> None:
    isolated = Workspace(LocalWorkspaceBackend(tmp_path))
    executor = PersonalExecutor(isolated)
    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="read_only",
        model=None,
        base_url=None,
        api_key=None,
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=executor,
    )
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4(), user_id=str(uuid4())),
        model=TestModel(),
        usage=RunUsage(),
    )
    result = await outer.tools["run_coding_agent"].function(ctx, "  ")
    assert "Describe the coding task first" in result
    assert not executor.closed


@pytest.mark.security
async def test_both_personal_harnesses_can_work_concurrently_without_sharing_accounts_or_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_path = tmp_path / "source"
    parent_path.mkdir()
    workspaces: dict[Harness, Workspace] = {}
    for harness in ("claude_code", "codex"):
        folder = tmp_path / harness
        folder.mkdir()
        workspaces[harness] = Workspace(LocalWorkspaceBackend(folder))
    entered: set[Harness] = set()
    closed: set[Harness] = set()
    both_started = anyio.Event()
    keys = {"claude_code": "private-claude-key", "codex": "private-codex-key"}

    class Executor:
        @asynccontextmanager
        async def session(
            self,
            ctx: RunContext[AgentDeps],
            *,
            harness: Harness,
            timeout_seconds: int,
            session: str = "main",
        ) -> AsyncGenerator[PersonalCodingTask]:
            entered.add(harness)
            if len(entered) == 2:
                both_started.set()
            await both_started.wait()
            try:
                yield PersonalCodingTask(
                    workspace=workspaces[harness],
                    account_id=uuid4(),
                    label=harness,
                    base_revision=harness,
                    result_archive=f"{harness}.zip",
                    api_key=SecretStr(keys[harness]),
                    redactions=(SecretStr(keys[harness]),),
                )
            finally:
                closed.add(harness)

    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="edit",
        model="claude-opus-5-5",
        effort="high",
        base_url=None,
        api_key="organization-key-must-not-be-used",
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=Executor(),
    )

    def build_inner(**options: object) -> FunctionToolset[AgentDeps]:
        selected = options["harness"]
        assert selected in ("claude_code", "codex")
        chosen: Harness = "codex" if selected == "codex" else "claude_code"
        assert options["api_key"] == keys[chosen]
        assert options["model"] == ("claude-opus-5-5" if chosen == "claude_code" else None)
        assert options["effort"] == ("high" if chosen == "claude_code" else None)
        toolset = FunctionToolset[AgentDeps]()

        async def run(
            ctx: RunContext[AgentDeps],
            task: str,
            fresh_session: bool = False,
            session: str = "main",
        ) -> str:
            assert ctx.workspace is workspaces[chosen] and not fresh_session and session == "main"
            await ctx.workspace.write_bytes("result.txt", chosen.encode())
            return CodingReport(
                harness=chosen, access="edit", outcome="completed", answer=keys[chosen]
            ).model_dump_json()

        toolset.add_function(run, name="run_coding_agent")
        return toolset

    monkeypatch.setattr(_toolset, "build_coding_toolset", build_inner)
    ctx = RunContext(
        deps=AgentDeps(organization_id=uuid4(), user_id=str(uuid4())),
        model=TestModel(),
        usage=RunUsage(),
        workspace=Workspace(LocalWorkspaceBackend(parent_path)),
    )
    reports: dict[Harness, str] = {}

    async def call(harness: Harness) -> None:
        reports[harness] = await outer.tools["run_coding_agent"].function(
            ctx, "Implement an independent task", harness=harness
        )

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(call, "claude_code")
            tasks.start_soon(call, "codex")
    assert entered == closed == {"claude_code", "codex"}
    assert not (parent_path / "result.txt").exists()
    for harness, report in reports.items():
        assert CodingReport.model_validate_json(report).harness == harness
        assert all(key not in report for key in keys.values())
        assert await workspaces[harness].read_bytes("result.txt") == harness.encode()


@pytest.mark.security
async def test_personal_codex_choice_cannot_bypass_read_only_access(tmp_path: Path) -> None:
    executor = PersonalExecutor(Workspace(LocalWorkspaceBackend(tmp_path)))
    outer = _toolset.build_coding_toolset(
        harness="claude_code",
        access="read_only",
        model=None,
        base_url=None,
        api_key=None,
        timeout_seconds=60,
        runs_on="personal_sandbox",
        personal_executor=executor,
    )
    ctx = RunContext(deps=AgentDeps(organization_id=uuid4()), model=TestModel(), usage=RunUsage())
    result = await outer.tools["run_coding_agent"].function(ctx, "Read the code", harness="codex")
    assert "Codex cannot run read-only" in result
    assert not executor.harnesses


async def test_a_waiting_account_task_starts_after_its_predecessor_releases() -> None:
    redis = MemoryRedis()
    first_started, release_first, waiting, second_started = (anyio.Event() for _ in range(4))
    order: list[str] = []

    async def first() -> None:
        async with account_lease("account", 60, redis=redis):
            order.append("first")
            first_started.set()
            await release_first.wait()
            order.append("first done")

    async def second() -> None:
        await first_started.wait()
        waiting.set()
        async with account_lease("account", 60, redis=redis, wait_seconds=2):
            order.append("second")
            second_started.set()

    with anyio.fail_after(3):
        async with anyio.create_task_group() as group:
            group.start_soon(first)
            group.start_soon(second)
            await waiting.wait()
            await anyio.sleep(0.05)
            assert not second_started.is_set()
            release_first.set()
    assert order == ["first", "first done", "second"]
    assert not redis.values


async def test_cancelling_or_expiring_a_waiter_never_releases_the_running_account() -> None:
    redis = MemoryRedis()
    async with account_lease("account", 60, redis=redis):
        token = redis.values["account"]
        with anyio.move_on_after(0.01):
            async with account_lease("account", 60, redis=redis, wait_seconds=2):
                pytest.fail("A waiter must not overlap the account's running task")
        with pytest.raises(ConflictError):
            async with account_lease("account", 60, redis=redis, wait_seconds=0.01):
                pytest.fail("A busy queue must expire")
        assert redis.values["account"] == token
    assert not redis.values


async def test_invalid_session_names_are_refused_before_account_or_workspace_access() -> None:
    from app.agents.capabilities.sandbox import SandboxConfig
    from app.agents.spec import AgentSpec
    from app.core.exceptions import BadRequestError
    from app.core.permissions import AuthContext
    from app.services.personal_coding import PersonalCodingSessionFactory

    owner, organization = uuid4(), uuid4()
    factory = PersonalCodingSessionFactory(
        AuthContext(user_id=owner, organization_id=organization, role="owner"),
        AgentSpec(name="Test"),
        SandboxConfig(backend="service"),
        uuid4(),
        redis=MemoryRedis(),
    )
    ctx = RunContext(
        deps=AgentDeps(organization_id=organization, user_id=str(owner)),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Task",
    )
    with pytest.raises(BadRequestError, match="valid coding session name"):
        async with factory.session(
            ctx, harness="claude_code", timeout_seconds=60, session="../private"
        ):
            pytest.fail("Invalid names must not reach execution")


@pytest.mark.security
@pytest.mark.parametrize("failure", ["transport", "exit"])
async def test_personal_codex_auth_cleanup_failure_cannot_be_called_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from pydantic_ai.exceptions import UserError
    from pydantic_ai.workspaces import CommandResult, WorkspaceError

    from tests.test_coding_agent import SIGNED_IN, _Store

    workspace = Workspace(LocalWorkspaceBackend(tmp_path))
    run = (
        AsyncMock(side_effect=WorkspaceError("transport unavailable"))
        if failure == "transport"
        else AsyncMock(return_value=CommandResult(stdout="", stderr="cleanup refused", exit_code=1))
    )
    monkeypatch.setattr(workspace, "run", run)
    ctx = RunContext(
        deps=AgentDeps(), model=TestModel(), usage=RunUsage(), prompt="Task", workspace=workspace
    )
    with pytest.raises(WorkspaceError if failure == "transport" else UserError):
        await _toolset._keep_rotated(
            ctx, _Store(), SIGNED_IN, env={"CODEX_HOME": "private"}, strict=True
        )


@pytest.mark.security
async def test_stopping_personal_codex_finishes_credential_readback_before_cancelling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.capabilities.coding_agent._task import Outcome
    from tests.test_coding_agent import _call, _Shell, _Store

    cleaned = False

    async def cancelled_task(*args: object, **kwargs: object) -> Outcome:
        scope.cancel()
        await anyio.sleep_forever()

    async def readback(*args: object, **kwargs: object) -> None:
        nonlocal cleaned
        await anyio.lowlevel.checkpoint()
        cleaned = True

    monkeypatch.setattr(_toolset, "run_detached", cancelled_task)
    monkeypatch.setattr(_toolset, "_keep_rotated", readback)
    with anyio.CancelScope() as scope:
        await _call(
            _Shell(),
            harness="codex",
            api_key=None,
            sign_in=lambda _org: _Store(),
            personal_isolated=True,
        )
    assert cleaned
