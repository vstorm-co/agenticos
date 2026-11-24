"""Owner refresh admission, generation fencing and renewable-auth cleanup."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from redis.exceptions import RedisError

from app.agents.capabilities.coding_agent._harness import codex_auth_file
from app.clients.redis import RedisClient
from app.core.exceptions import AuthorizationError, BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.coding_account import CodingAccount
from app.schemas.coding_account import (
    ProviderModelCatalog,
    ProviderUsageSnapshot,
    ProviderUsageWindow,
)
from app.services.coding_account_usage import CodingAccountUsageService
from app.services.coding_account_usage import _refresh as worker
from app.services.coding_account_usage import _runtime as runtime
from app.services.coding_account_usage import _service as service_module
from app.worker.jobs import RefreshCodingAccountUsage

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def account() -> CodingAccount:
    return CodingAccount(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        generation=uuid4(),
        harness="codex",
        secret_kind="openai_codex",
        label="Personal",
        enabled=True,
        is_default=True,
        pool_member=True,
        sealed_secret="fixture-sealed-credential",
        key_version=1,
    )


def context(row: CodingAccount) -> AuthContext:
    return AuthContext(user_id=row.user_id, organization_id=row.organization_id, role="owner")


def observation() -> runtime.Observation:
    now = datetime.now(UTC)
    return runtime.Observation(
        usage=ProviderUsageSnapshot(
            status="available",
            source="native_runtime",
            observed_at=now,
            valid_until=now + timedelta(minutes=5),
            windows=[ProviderUsageWindow(name="primary", used=20, limit=100, unit="percent")],
        ),
        model_catalog=ProviderModelCatalog(
            status="advertised",
            source="native_runtime",
            observed_at=now,
            valid_until=now + timedelta(minutes=5),
            model_ids=["gpt-5.4"],
            reason_code=None,
        ),
    )


def envelope(row: CodingAccount) -> service_module.CachedObservation:
    return service_module.CachedObservation(
        organization_id=row.organization_id,
        user_id=row.user_id,
        account_id=row.id,
        generation=row.generation,
        observation=observation(),
    )


def redis() -> AsyncMock:
    client = AsyncMock(spec=RedisClient)
    client.get.return_value = None
    client.set.return_value = True
    return client


def payload(row: CodingAccount) -> RefreshCodingAccountUsage:
    return RefreshCodingAccountUsage(
        organization_id=row.organization_id,
        user_id=row.user_id,
        account_id=row.id,
        generation=row.generation,
        request_id=uuid4(),
    )


@asynccontextmanager
async def database() -> AsyncGenerator[AsyncMock]:
    yield AsyncMock()


async def test_refresh_queues_ids_only_and_owner_reads_the_cached_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    owned = AsyncMock(return_value=row)
    monkeypatch.setattr(service_module.account_repo, "get", owned)
    monkeypatch.setattr(service_module.member_repo, "get_active", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        service_module.job_repo, "latest_with_dedupe_key", AsyncMock(return_value=None)
    )
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(service_module, "enqueue", enqueue)
    service = CodingAccountUsageService(AsyncMock(), client)
    result = await service.refresh(context(row), row.id, row.generation)
    assert result.refresh_pending and result.usage.status == "unknown"
    queued = enqueue.await_args.args[2]
    assert set(queued.model_dump()) == {
        "organization_id",
        "user_id",
        "account_id",
        "generation",
        "request_id",
    }
    assert queued.user_id == row.user_id and queued.account_id == row.id
    assert enqueue.await_args.kwargs["dedupe_active"] is True
    assert owned.await_args.kwargs == {
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "account_id": row.id,
        "locked": True,
    }
    client.get.return_value = envelope(row).model_dump_json()
    read = await service.read(context(row), row.id)
    assert read.usage.status == "available" and read.model_catalog.status == "advertised"
    assert "fixture-sealed-credential" not in read.model_dump_json()
    client.get.assert_awaited_with(service_module.account_key(row))


@pytest.mark.parametrize("case", ["missing", "inactive", "generation", "disabled", "unsupported"])
async def test_refresh_refuses_missing_authority_or_consent(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    row, client = account(), redis()
    expected = row.generation
    if case == "generation":
        expected = uuid4()
    if case == "disabled":
        row.enabled = False
    if case == "unsupported":
        row.secret_kind = "api_key"
    monkeypatch.setattr(
        service_module.member_repo,
        "get_active",
        AsyncMock(return_value=None if case == "inactive" else object()),
    )
    monkeypatch.setattr(
        service_module.account_repo,
        "get",
        AsyncMock(return_value=None if case == "missing" else row),
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(service_module, "enqueue", enqueue)
    with pytest.raises((AuthorizationError, NotFoundError, ConflictError, BadRequestError)):
        await CodingAccountUsageService(AsyncMock(), client).refresh(context(row), row.id, expected)
    enqueue.assert_not_awaited()
    client.get.assert_not_awaited()


@pytest.mark.parametrize("field", ["organization_id", "user_id", "account_id", "generation"])
async def test_cached_observation_cannot_cross_account_owner_or_generation(field: str) -> None:
    row, client = account(), redis()
    wrong = envelope(row).model_copy(update={field: uuid4()})
    client.get.return_value = wrong.model_dump_json()
    assert await CodingAccountUsageService(AsyncMock(), client).cached(row) is None


async def test_cache_outage_is_unknown_but_programming_errors_are_not_hidden() -> None:
    row, client = account(), redis()
    service = CodingAccountUsageService(AsyncMock(), client)
    client.get.side_effect = RedisError("fixture-private-cache-error")
    assert await service.cached(row) is None
    client.get.side_effect = RuntimeError("unconnected client bug")
    with pytest.raises(RuntimeError, match="unconnected client bug"):
        await service.cached(row)


async def test_stale_usage_and_models_become_unknown_without_a_provider_call() -> None:
    row, client = account(), redis()
    old = envelope(row)
    old.observation.usage.valid_until = datetime.now(UTC) - timedelta(seconds=1)
    old.observation.model_catalog.valid_until = old.observation.usage.valid_until
    client.get.return_value = old.model_dump_json()
    read = await CodingAccountUsageService(AsyncMock(), client).cached(row)
    assert read is not None and read.usage.status == "unknown"
    assert read.model_catalog.status == "unknown" and read.model_catalog.model_ids == []


async def test_disabled_and_unsupported_accounts_do_not_read_provider_cache() -> None:
    row, client = account(), redis()
    service = CodingAccountUsageService(AsyncMock(), client)
    row.enabled = False
    assert (await service._read(row)).usage.status == "disabled"
    row.enabled, row.secret_kind = True, "api_key"
    assert (await service._read(row)).usage.reason_code == "telemetry_unsupported"
    client.get.assert_not_awaited()


async def test_active_refresh_is_shared_and_recent_completion_has_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    service = CodingAccountUsageService(AsyncMock(), client)
    monkeypatch.setattr(service, "_account", AsyncMock(return_value=row))
    job = SimpleNamespace(status="running", created_at=datetime.now(UTC))
    monkeypatch.setattr(
        service_module.job_repo, "latest_with_dedupe_key", AsyncMock(return_value=job)
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(service_module, "enqueue", enqueue)
    assert (await service.refresh(context(row), row.id, row.generation)).refresh_pending
    job.status = "completed"
    with pytest.raises(ConflictError, match="thirty seconds"):
        await service.refresh(context(row), row.id, row.generation)
    enqueue.assert_not_awaited()
    job.created_at = datetime.now(UTC) - timedelta(seconds=31)
    assert (await service.refresh(context(row), row.id, row.generation)).refresh_pending
    enqueue.assert_awaited_once()


async def test_runtime_auth_stays_in_env_rotation_is_preserved_and_home_is_removed() -> None:
    written = OpenAICodexCredentials(
        access_token="fixture-old-access",
        refresh_token="fixture-old-refresh",
        account_id="provider-account",
    )
    rotated = OpenAICodexCredentials(
        access_token="fixture-new-access",
        refresh_token="fixture-new-refresh",
        account_id="provider-account",
    )
    source = SimpleNamespace(
        load=AsyncMock(return_value=written), swap=AsyncMock(return_value=True)
    )
    run = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, stdout=""),
            SimpleNamespace(exit_code=0, stdout=observation().model_dump_json()),
            SimpleNamespace(exit_code=0, stdout=codex_auth_file(rotated)),
        ]
    )
    result = await runtime.read_usage(SimpleNamespace(run=run), source)
    assert result.usage.status == "available"
    source.swap.assert_awaited_once_with(written, rotated)
    stage, probe, cleanup = run.await_args_list
    assert written.access_token in stage.kwargs["env"]["AGENTICOS_CODEX_AUTH"]
    assert probe.kwargs["env"]["AGENTICOS_CODEX_EXPECTED_ACCOUNT"] == "provider-account"
    assert cleanup.args[0] == runtime.READ_AUTH
    assert stage.kwargs["env"]["CODEX_HOME"] == cleanup.kwargs["env"]["CODEX_HOME"]
    for call in run.await_args_list:
        assert "fixture-old-access" not in str(call.args)
        assert call.kwargs["timeout"] <= 65


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("fixture-private-error"),
        SimpleNamespace(exit_code=0, stdout='{"reason_code":"fixture-private-error"}'),
        SimpleNamespace(exit_code=0, stdout="not-json fixture-private-error"),
    ],
)
async def test_runtime_failure_is_sanitized_and_still_cleans_up(
    failure: object, caplog: pytest.LogCaptureFixture
) -> None:
    credentials = OpenAICodexCredentials(
        access_token="fixture-token", refresh_token="fixture-refresh", account_id="provider-account"
    )
    run = AsyncMock(
        side_effect=[
            SimpleNamespace(exit_code=0, stdout=""),
            failure,
            SimpleNamespace(exit_code=0, stdout="{}"),
        ]
    )
    source = SimpleNamespace(load=AsyncMock(return_value=credentials), swap=AsyncMock())
    with pytest.raises(runtime.ProbeUnavailable) as refused:
        await runtime.read_usage(SimpleNamespace(run=run), source)
    assert "fixture-private-error" not in str(refused.value) + caplog.text
    assert run.await_args_list[-1].args[0] == runtime.READ_AUTH
    source.swap.assert_not_awaited()


@pytest.mark.parametrize(
    "case", ["job", "attempt", "membership", "account", "disabled", "generation"]
)
async def test_worker_rechecks_attempt_owner_and_generation(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = account()
    request = payload(row)
    if case == "disabled":
        row.enabled = False
    if case == "generation":
        row.generation = uuid4()
    job = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(
        worker.job_repo,
        "get_by_idempotency_key",
        AsyncMock(return_value=None if case == "job" else job),
    )
    monkeypatch.setattr(
        worker.job_repo,
        "get_for_attempt",
        AsyncMock(return_value=None if case == "attempt" else job),
    )
    monkeypatch.setattr(
        worker,
        "job_context",
        AsyncMock(return_value=None if case == "membership" else context(row)),
    )
    monkeypatch.setattr(
        worker.account_repo, "get", AsyncMock(return_value=None if case == "account" else row)
    )
    assert await worker.current(AsyncMock(), request, 3) is None


async def test_stale_worker_cannot_publish_or_overwrite_a_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = redis()
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "current", AsyncMock(return_value=None))
    await worker.publish(payload(account()), 2, client, observation(), None)
    client.set.assert_not_awaited()


async def test_transient_failure_preserves_valid_evidence_but_identity_mismatch_clears_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    client.get.return_value = envelope(row).model_dump_json()
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "current", AsyncMock(return_value=(context(row), row)))
    request = payload(row)
    await worker.publish(request, 1, client, None, "probe_timeout")
    client.set.assert_not_awaited()
    await worker.publish(request, 1, client, None, "provider_identity_mismatch")
    stored = service_module.CachedObservation.model_validate_json(client.set.await_args.args[1])
    assert stored.observation.usage.reason_code == "provider_identity_mismatch"
    assert stored.observation.usage.status == "unknown"
    assert stored.observation.model_catalog.model_ids == []
    assert client.set.await_args.args[0] == service_module.account_key(row)
    assert client.set.await_args.kwargs["ttl"] == 300


@pytest.mark.parametrize("raw", ["not-json", "{}", "x" * 65537])
async def test_bad_or_oversize_cache_records_stay_unknown(raw: str) -> None:
    row, client = account(), redis()
    client.get.return_value = raw
    assert await CodingAccountUsageService(AsyncMock(), client).cached(row) is None


async def test_account_list_enriches_metadata_without_exposing_sealed_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    client.get.return_value = envelope(row).model_dump_json()
    monkeypatch.setattr(service_module.CodingAccountService, "mine", AsyncMock(return_value=[row]))
    monkeypatch.setattr(
        service_module.job_repo,
        "latest_with_dedupe_key",
        AsyncMock(return_value=SimpleNamespace(status="running")),
    )
    result = await CodingAccountUsageService(AsyncMock(), client).mine(context(row))
    assert len(result) == 1 and result[0].usage_refresh_pending
    assert result[0].usage.status == "available"
    assert "fixture-sealed-credential" not in result[0].model_dump_json()


@pytest.mark.parametrize("case", ["staging", "execution", "oversize", "identity", "cleanup"])
async def test_runtime_boundaries_always_attempt_private_home_cleanup(
    case: str, caplog: pytest.LogCaptureFixture
) -> None:
    credentials = OpenAICodexCredentials(
        access_token="fixture-token", refresh_token="fixture-refresh", account_id="provider-account"
    )
    source = SimpleNamespace(load=AsyncMock(return_value=credentials), swap=AsyncMock())
    stage = SimpleNamespace(exit_code=1 if case == "staging" else 0, stdout="")
    answer = SimpleNamespace(
        exit_code=1 if case == "execution" else 0,
        stdout=(
            "x" * 65537
            if case == "oversize"
            else '{"reason_code":"provider_identity_mismatch"}'
            if case == "identity"
            else observation().model_dump_json()
        ),
    )
    cleanup = (
        RuntimeError("fixture-private-cleanup-error")
        if case == "cleanup"
        else SimpleNamespace(exit_code=0, stdout="{}")
    )
    run = AsyncMock(side_effect=[stage, cleanup] if case == "staging" else [stage, answer, cleanup])
    if case == "cleanup":
        assert (
            await runtime.read_usage(SimpleNamespace(run=run), source)
        ).usage.status == "available"
        assert "fixture-private-cleanup-error" not in caplog.text
    else:
        with pytest.raises(runtime.ProbeUnavailable):
            await runtime.read_usage(SimpleNamespace(run=run), source)
    assert run.await_args_list[-1].args[0] == runtime.READ_AUTH


@pytest.mark.parametrize("kind", ["docker", "daytona"])
async def test_usage_workspace_requires_managed_docker_and_has_no_invented_run(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.sandbox_workspace import SandboxWorkspaceService

    row = account()
    service = SandboxWorkspaceService(AsyncMock())
    connection_id, request_id = uuid4(), uuid4()
    monkeypatch.setattr(
        service.connections,
        "resolve",
        AsyncMock(return_value=SimpleNamespace(kind=kind, row=SimpleNamespace(id=connection_id))),
    )
    backend = SimpleNamespace(ref=None)
    capability = SimpleNamespace(backend=lambda _opened: backend)
    selected = []

    def capability_for(resolved: object, key: str, **options: object) -> object:
        selected.append((resolved, key, options))
        return capability

    monkeypatch.setattr(service, "_service_capability", capability_for)
    if kind != "docker":
        with pytest.raises(BadRequestError, match="managed Docker"):
            await service.open_account_usage(context(row), request_id=request_id)
        assert selected == []
    else:
        opened = await service.open_account_usage(context(row), request_id=request_id)
        assert opened.scope == "run" and opened.row_id is None
        assert opened.connection_id == connection_id and opened.workspace.run_id is None
        assert selected[0][2] == {"runtime": "workbench", "tenant": str(row.organization_id)}
        assert request_id.hex in opened.scope_key


@pytest.mark.parametrize("failed", [False, True])
async def test_probe_serializes_renewable_auth_and_always_closes_workspace(
    failed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    row, client = account(), redis()
    request = payload(row)
    opened = SimpleNamespace(workspace=object())
    service = SimpleNamespace(open_account_usage=AsyncMock(return_value=opened), close=AsyncMock())
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "SandboxWorkspaceService", lambda _db: service)
    read = AsyncMock(
        side_effect=runtime.ProbeUnavailable() if failed else None, return_value=observation()
    )
    monkeypatch.setattr(worker, "read_usage", read)
    if failed:
        with pytest.raises(runtime.ProbeUnavailable):
            await worker.probe(request, context(row), client)
    else:
        assert (await worker.probe(request, context(row), client)).usage.status == "available"
    service.close.assert_awaited_once_with(opened)
    lease = f"personal-coding:{row.organization_id}:{row.user_id}:{row.id}"
    assert client.set.await_args.args[0] == lease and client.set.await_args.kwargs["nx"] is True
    assert client.delete_if_equal.await_args.args[0] == lease


@pytest.mark.parametrize(
    "failure,reason",
    [
        (None, None),
        (runtime.ProbeUnavailable("runtime_version_unsupported"), "runtime_version_unsupported"),
        (ConflictError(), "provider_busy"),
        (BadRequestError(), "telemetry_unsupported"),
        (TimeoutError(), "probe_timeout"),
    ],
)
async def test_durable_handler_publishes_only_under_fence_and_returns_no_private_result(
    failure: Exception | None,
    reason: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    request, observed = payload(row), observation()
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "current_attempt_number", lambda: 7)
    monkeypatch.setattr(worker, "current", AsyncMock(return_value=(context(row), row)))
    monkeypatch.setattr(worker, "RedisClient", lambda: client)
    monkeypatch.setattr(worker, "probe", AsyncMock(side_effect=failure, return_value=observed))
    publish = AsyncMock()
    monkeypatch.setattr(worker, "publish", publish)
    assert await worker.refresh_usage(request) is None
    publish.assert_awaited_once_with(
        request, 7, client, observed if failure is None else None, reason
    )
    client.connect.assert_awaited_once()
    client.close.assert_awaited_once()


async def test_stale_durable_handler_never_connects_or_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "current_attempt_number", lambda: 2)
    monkeypatch.setattr(worker, "current", AsyncMock(return_value=None))
    probe = AsyncMock()
    monkeypatch.setattr(worker, "probe", probe)
    assert await worker.refresh_usage(payload(account())) is None
    probe.assert_not_awaited()


async def test_successful_publication_binds_the_current_owner_and_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "current", AsyncMock(return_value=(context(row), row)))
    observed = observation()
    await worker.publish(payload(row), 4, client, observed, None)
    saved = service_module.CachedObservation.model_validate_json(client.set.await_args.args[1])
    assert saved.organization_id == row.organization_id and saved.user_id == row.user_id
    assert saved.account_id == row.id and saved.generation == row.generation
    assert saved.observation == observed


async def test_cancellation_keeps_rotated_grant_and_releases_private_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, client = account(), redis()
    request = payload(row)
    waiting, cleaned = anyio.Event(), anyio.Event()
    written = OpenAICodexCredentials(
        access_token="fixture-old-access",
        refresh_token="fixture-old-refresh",
        account_id="provider-account",
    )
    rotated = OpenAICodexCredentials(
        access_token="fixture-new-access",
        refresh_token="fixture-new-refresh",
        account_id="provider-account",
    )
    source = SimpleNamespace(
        load=AsyncMock(return_value=written), swap=AsyncMock(return_value=True)
    )

    async def run(command: object, **_options: object) -> object:
        if command == runtime.WRITE_AUTH:
            return SimpleNamespace(exit_code=0, stdout="")
        if command == runtime.READ_AUTH:
            cleaned.set()
            return SimpleNamespace(exit_code=0, stdout=codex_auth_file(rotated))
        waiting.set()
        return await anyio.sleep_forever()

    opened = SimpleNamespace(workspace=SimpleNamespace(run=run))
    service = SimpleNamespace(open_account_usage=AsyncMock(return_value=opened), close=AsyncMock())
    monkeypatch.setattr(worker, "get_worker_db_context", database)
    monkeypatch.setattr(worker, "SandboxWorkspaceService", lambda _db: service)
    monkeypatch.setattr(worker, "PersonalCodexCredentials", lambda *_ids: source)
    with anyio.fail_after(2):
        async with anyio.create_task_group() as group:
            group.start_soon(worker.probe, request, context(row), client)
            await waiting.wait()
            group.cancel_scope.cancel()
    assert cleaned.is_set()
    source.swap.assert_awaited_once_with(written, rotated)
    service.close.assert_awaited_once_with(opened)
    client.delete_if_equal.assert_awaited_once()
