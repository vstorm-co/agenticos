"""A profile credential never falls back to a tool key or shares an execution workspace."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

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
from app.core.exceptions import BadRequestError, ConflictError
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


def _pool_account(organization_id: UUID, user_id: UUID, label: str):
    from app.db.models.coding_account import CodingAccount

    return CodingAccount(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        harness="codex",
        label=label,
        secret_kind="openai_codex",
        sealed_secret="sealed",
        key_version=1,
        enabled=True,
        generation=uuid4(),
        is_default=label == "primary",
        pool_member=True,
        provider_identity_fingerprint=label.encode().hex().ljust(64, "0"),
    )


def _personal_factory_context(organization_id: UUID, user_id: UUID):
    from pydantic_ai.tools import RunContext
    from pydantic_ai.usage import RunUsage

    from app.agents.deps import AgentDeps

    return RunContext(
        deps=AgentDeps(
            organization_id=organization_id,
            user_id=str(user_id),
            conversation_id=uuid4(),
        ),
        model=TestModel(),
        usage=RunUsage(),
        prompt="Run the coding task",
    )


def _personal_session_factory(organization_id: UUID, user_id: UUID, redis: MemoryRedis):
    from app.agents.capabilities.sandbox import SandboxConfig
    from app.agents.spec import AgentSpec
    from app.core.permissions import AuthContext
    from app.services.personal_coding import PersonalCodingSessionFactory

    return PersonalCodingSessionFactory(
        AuthContext(user_id=user_id, organization_id=organization_id, role="member"),
        AgentSpec(name="Test"),
        SandboxConfig(backend="service", session_scope="run"),
        uuid4(),
        redis=redis,
    )


async def test_busy_pool_lease_selects_the_next_account_before_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import personal_coding as module
    from app.services.personal_coding import PersonalCodingSessionFactory

    owner, organization = uuid4(), uuid4()
    first, second = (
        _pool_account(organization, owner, "primary"),
        _pool_account(organization, owner, "secondary"),
    )
    redis = MemoryRedis()
    factory = _personal_session_factory(organization, owner, redis)
    attempted = []

    @asynccontextmanager
    async def connection():
        yield object()

    @asynccontextmanager
    async def isolated(_self, _ctx, account, _harness, *, selection_reason):
        attempted.append((account.id, selection_reason))
        yield account

    monkeypatch.setattr(module, "get_db_context", connection)
    monkeypatch.setattr(
        module.conversation_share_repo,
        "get_shares_for_conversation",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        PersonalCodingSessionFactory, "_accounts", AsyncMock(return_value=[first, second])
    )
    monkeypatch.setattr(PersonalCodingSessionFactory, "_isolated", isolated)

    key = f"personal-coding:{organization}:{owner}:{first.id}"
    async with account_lease(key, 60, redis=redis):
        async with factory.session(
            _personal_factory_context(organization, owner), harness="codex", timeout_seconds=60
        ) as selected:
            assert selected is second
        assert attempted == [(second.id, "opt_in_pool")]
        assert key in redis.values
        assert f"personal-coding:{organization}:{owner}:{second.id}" not in redis.values


@pytest.mark.parametrize("state", ["empty", "no_default", "disabled_default", "disabled_pool"])
async def test_account_selection_refuses_unavailable_accounts(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from app.services import personal_coding as module

    owner, organization = uuid4(), uuid4()
    account = _pool_account(organization, owner, "primary")
    account.pool_member = state == "disabled_pool"
    account.enabled = state not in {"disabled_default", "disabled_pool"}
    account.is_default = state != "no_default"
    factory = _personal_session_factory(organization, owner, MemoryRedis())

    @asynccontextmanager
    async def connection() -> AsyncGenerator[object]:
        yield object()

    monkeypatch.setattr(module, "get_db_context", connection)
    monkeypatch.setattr(
        module.account_repo,
        "list_for",
        AsyncMock(return_value=[] if state == "empty" else [account]),
    )
    with pytest.raises(BadRequestError, match=r"Enable an account|Choose and enable"):
        await factory._accounts("codex")


async def test_all_busy_accounts_are_refused_without_entering_a_provider_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import personal_coding as module
    from app.services.personal_coding import PersonalCodingSessionFactory

    owner, organization = uuid4(), uuid4()
    account = _pool_account(organization, owner, "primary")
    redis = MemoryRedis()
    factory = _personal_session_factory(organization, owner, redis)

    @asynccontextmanager
    async def connection() -> AsyncGenerator[object]:
        yield object()

    monkeypatch.setattr(module, "get_db_context", connection)
    monkeypatch.setattr(
        module.conversation_share_repo, "get_shares_for_conversation", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        PersonalCodingSessionFactory, "_accounts", AsyncMock(return_value=[account])
    )
    key = f"personal-coding:{organization}:{owner}:{account.id}"
    async with account_lease(key, 60, redis=redis):
        held = redis.values[key]
        with pytest.raises(ConflictError, match="Every eligible coding account"):
            async with factory.session(
                _personal_factory_context(organization, owner), harness="codex", timeout_seconds=60
            ):
                pytest.fail("A busy account must not enter a provider session")
        assert redis.values[key] == held
    assert not redis.values


async def test_an_error_after_admission_never_starts_a_replacement_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import personal_coding as module
    from app.services.personal_coding import PersonalCodingSessionFactory

    owner, organization = uuid4(), uuid4()
    first, second = (
        _pool_account(organization, owner, "primary"),
        _pool_account(organization, owner, "secondary"),
    )
    factory = _personal_session_factory(organization, owner, MemoryRedis())
    attempted = []

    @asynccontextmanager
    async def connection():
        yield object()

    @asynccontextmanager
    async def isolated(_self, _ctx, account, _harness, *, selection_reason):
        attempted.append((account.id, selection_reason))
        yield account

    monkeypatch.setattr(module, "get_db_context", connection)
    monkeypatch.setattr(
        module.conversation_share_repo,
        "get_shares_for_conversation",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        PersonalCodingSessionFactory, "_accounts", AsyncMock(return_value=[first, second])
    )
    monkeypatch.setattr(PersonalCodingSessionFactory, "_isolated", isolated)

    with pytest.raises(ConflictError, match="acceptance is uncertain"):
        async with factory.session(
            _personal_factory_context(organization, owner), harness="codex", timeout_seconds=60
        ):
            raise ConflictError(message="Provider acceptance is uncertain")
    assert attempted == [(first.id, "opt_in_pool")]


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
        self.account_id = uuid4()
        self.closed = False

    @asynccontextmanager
    async def session(
        self, ctx: RunContext[AgentDeps], *, harness: Harness, timeout_seconds: int
    ) -> AsyncGenerator[PersonalCodingTask]:
        try:
            yield PersonalCodingTask(
                workspace=self.workspace,
                account_id=self.account_id,
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
            ctx: RunContext[AgentDeps], task: str, fresh_session: bool = False
        ) -> str | dict[str, str]:
            assert ctx.workspace is isolated and ctx.deps.subagent_events is None
            assert fresh_session
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
    assert report.account_id == str(executor.account_id)
    assert report.selection_reason == "manual_default"
    assert report.execution == "isolated_task" and report.result_archive
    assert report.account_id is not None and report.selection_reason == "manual_default"
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
