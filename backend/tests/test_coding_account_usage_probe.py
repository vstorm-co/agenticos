"""Pinned native metadata protocol, with fake processes and no provider requests."""

import asyncio
import json
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.coding_account_usage import _native_probe as native

pytestmark = [pytest.mark.anyio, pytest.mark.security]


def quota(**changes: object) -> dict[str, object]:
    return {
        "accountId": "selected-account",
        "ordinaryUsageAllowed": True,
        "rateLimits": {
            "primary": {"usedPercent": 15, "windowDurationMins": 300, "resetsAt": 1900000000}
        },
        "privateField": "fixture-private-value",
        **changes,
    }


def catalog(now: datetime, **changes: object) -> dict[str, object]:
    return {
        "client_version": native.VERSION,
        "identity": "private-auth-identity",
        "fetched_at": now.isoformat(),
        "models": [{"slug": "gpt-5.4"}],
        **changes,
    }


def test_readiness_requires_provider_evidence_and_percent_keeps_its_unit() -> None:
    now = datetime.now(UTC)
    value = native.usage_snapshot(quota(), "selected-account", now)
    assert value["status"] == "available"
    assert value["windows"] == [
        {
            "name": "primary",
            "used": 15,
            "limit": 100,
            "unit": "percent",
            "resets_at": datetime.fromtimestamp(1900000000, UTC).isoformat(),
            "window_duration_minutes": 300,
        }
    ]
    assert value["valid_until"] == (now + timedelta(minutes=5)).isoformat()
    assert "fixture-private-value" not in json.dumps(value)
    for response in (quota(ordinaryUsageAllowed=None), quota(rateLimits={})):
        assert native.usage_snapshot(response, "selected-account", now)["status"] == "unknown"


@pytest.mark.parametrize("account", [None, "other-account", ""])
def test_provider_identity_mismatch_refuses_all_observations(account: object) -> None:
    with pytest.raises(native.ProbeFailure, match="provider_identity_mismatch"):
        native.usage_snapshot(quota(accountId=account), "selected-account", datetime.now(UTC))


@pytest.mark.parametrize(
    "reached,status",
    [
        ("rate_limit_reached", "rate_limited"),
        ("workspace_owner_credits_depleted", "quota_exhausted"),
        ("workspace_member_credits_depleted", "quota_exhausted"),
        ("workspace_owner_usage_limit_reached", "quota_exhausted"),
        ("workspace_member_usage_limit_reached", "quota_exhausted"),
        (None, "capacity_unavailable"),
    ],
)
def test_explicit_provider_failure_types(reached: str | None, status: str) -> None:
    value = native.usage_snapshot(
        quota(ordinaryUsageAllowed=False, rateLimits={"rateLimitReachedType": reached}),
        "selected-account",
        datetime.now(UTC),
    )
    assert value["status"] == status


@pytest.mark.parametrize(
    "window",
    [
        {"usedPercent": True},
        {"usedPercent": -1},
        {"usedPercent": 2, "windowDurationMins": 0},
        {"usedPercent": 2, "resetsAt": "tomorrow"},
        {"usedPercent": 2, "resetsAt": 253402300800},
    ],
)
def test_malformed_windows_are_refused(window: object) -> None:
    with pytest.raises(native.ProbeFailure, match="telemetry_unavailable"):
        native.usage_snapshot(
            quota(rateLimits={"primary": window}), "selected-account", datetime.now(UTC)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_version": "0.159.0"},
        {"identity": None},
        {"identity": ""},
        {"fetched_at": "invalid"},
        {"fetched_at": None},
        {"fetched_at": "2020-01-01T00:00:00+00:00"},
        {"fetched_at": "2099-01-01T00:00:00+00:00"},
        {"fetched_at": "2026-01-01T00:00:00"},
        {"models": None},
        {"models": []},
        {"models": [{}] * 201},
    ],
)
def test_stale_bundled_or_unscoped_models_do_not_prove_advertisement(
    changes: dict[str, object],
) -> None:
    now = datetime.now(UTC)
    value = native.advertised_models(catalog(now, **changes), {"gpt-5.4"}, now, now)
    assert value["status"] == "unknown" and value["model_ids"] == []


class Peer:
    def __init__(
        self,
        home: Path,
        response: dict[str, object],
        *,
        remote_cache: bool = True,
        model_failure: str | None = None,
    ) -> None:
        self.home, self.response, self.remote_cache = home, response, remote_cache
        self.model_failure = model_failure
        self.rotated_account = "selected-account"
        self.messages: list[dict[str, object]] = []
        self.stdout = asyncio.StreamReader()
        self.stdin = self
        self.drain = AsyncMock()

    def write(self, encoded: bytes) -> None:
        request = json.loads(encoded)
        self.messages.append(request)
        if request["method"] == "initialized":
            return
        answer: object = {}
        if request["method"] == "account/rateLimits/read":
            answer = self.response
        elif request["method"] == "model/list":
            (self.home / "auth.json").write_text(
                json.dumps(
                    {
                        "tokens": {
                            "account_id": self.rotated_account,
                            "access_token": "fixture-rotated-token",
                        }
                    }
                ),
                encoding="utf-8",
            )
            if self.model_failure == "error":
                self.stdout.feed_data(
                    json.dumps(
                        {"id": request["id"], "error": {"message": "fixture-private-model-error"}}
                    ).encode()
                    + b"\n"
                )
                return
            answer = {"data": [{"model": "gpt-5.4", "description": "private"}], "nextCursor": None}
            if self.model_failure == "pagination":
                answer["nextCursor"] = 5
            if self.remote_cache:
                (self.home / "models_cache.json").write_text(
                    json.dumps(catalog(datetime.now(UTC))), encoding="utf-8"
                )
        self.stdout.feed_data(json.dumps({"id": request["id"], "result": answer}).encode() + b"\n")


def processes(
    monkeypatch: pytest.MonkeyPatch, peer: Peer, *, version: bytes = b"codex-cli 0.160.0\n"
) -> tuple[AsyncMock, AsyncMock]:
    (peer.home / "auth.json").write_text(
        json.dumps(
            {"tokens": {"account_id": "selected-account", "access_token": "fixture-original-token"}}
        ),
        encoding="utf-8",
    )
    first = SimpleNamespace(
        stdout=SimpleNamespace(read=AsyncMock(return_value=version)), wait=AsyncMock(), returncode=0
    )
    start, stop = AsyncMock(side_effect=[first, peer]), AsyncMock()
    monkeypatch.setattr(native, "start", start)
    monkeypatch.setattr(native, "stop", stop)
    return start, stop


@pytest.mark.parametrize("remote_cache", [True, False])
async def test_probe_only_reads_metadata_in_selected_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote_cache: bool
) -> None:
    peer = Peer(tmp_path, quota(), remote_cache=remote_cache)
    start, stop = processes(monkeypatch, peer)
    result = await native.collect(tmp_path, "selected-account")
    assert [item["method"] for item in peer.messages] == [
        "initialize",
        "initialized",
        "account/rateLimits/read",
        "model/list",
    ]
    assert peer.messages[2]["params"] == {
        "excludeResetCreditDetails": True,
        "supportsLunaReserve": False,
    }
    assert [call.args for call in start.await_args_list] == [
        ("--version",),
        ("app-server", "--listen", "stdio://"),
    ]
    assert result["usage"]["status"] == "available"
    assert result["model_catalog"]["status"] == ("advertised" if remote_cache else "unknown")
    for forbidden in (
        "selected-account",
        "fixture-private-value",
        "private-auth",
        "description",
        "entitlement",
    ):
        assert forbidden not in json.dumps(result)
    assert stop.await_count == 2


@pytest.mark.parametrize("model_failure", ["error", "pagination"])
async def test_model_discovery_failure_preserves_verified_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model_failure: str,
) -> None:
    peer = Peer(tmp_path, quota(), model_failure=model_failure)
    _start, stop = processes(monkeypatch, peer)
    result = await native.collect(tmp_path, "selected-account")
    assert result["usage"]["status"] == "available"
    assert result["usage"]["windows"][0]["used"] == 15
    assert result["model_catalog"]["status"] == "unknown"
    assert result["model_catalog"]["model_ids"] == []
    assert "fixture-private-model-error" not in json.dumps(result)
    stop.assert_awaited_with(peer)


async def test_native_rotation_to_another_account_refuses_the_catalog_and_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    peer = Peer(tmp_path, quota())
    peer.rotated_account = "another-account"
    _start, stop = processes(monkeypatch, peer)
    with pytest.raises(native.ProbeFailure, match="provider_identity_mismatch"):
        await native.collect(tmp_path, "selected-account")
    assert any(item["method"] == "model/list" for item in peer.messages)
    stop.assert_awaited_with(peer)


@pytest.mark.parametrize("contents", [None, "not-json", "{}", "x" * 32769])
def test_final_identity_requires_bounded_staged_auth_file(
    tmp_path: Path, contents: str | None
) -> None:
    if contents is not None:
        (tmp_path / "auth.json").write_text(contents, encoding="utf-8")
    with pytest.raises(native.ProbeFailure, match="provider_identity_mismatch"):
        native.verify_auth_identity(tmp_path, "selected-account")


async def test_mismatch_stops_before_model_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    peer = Peer(tmp_path, quota(accountId="other-account"))
    _start, stop = processes(monkeypatch, peer)
    with pytest.raises(native.ProbeFailure, match="provider_identity_mismatch"):
        await native.collect(tmp_path, "selected-account")
    assert not any(item["method"] == "model/list" for item in peer.messages)
    stop.assert_awaited_with(peer)


async def test_wrong_version_and_existing_cache_are_refused_before_provider_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    start, _stop = processes(monkeypatch, Peer(tmp_path, quota()), version=b"codex-cli 0.159.0\n")
    with pytest.raises(native.ProbeFailure, match="runtime_version_unsupported"):
        await native.collect(tmp_path, "selected-account")
    assert start.await_count == 1
    (tmp_path / "models_cache.json").write_text("{}", encoding="utf-8")
    with pytest.raises(native.ProbeFailure, match="model_catalog_unverified"):
        await native.collect(tmp_path, "selected-account")
    assert start.await_count == 1


async def test_rpc_suppresses_provider_errors_and_bounds_notifications() -> None:
    for lines in (
        [{"id": 1, "error": {"message": "fixture-secret-error"}}],
        [{"method": "ignored"}] * 32,
        [True],
    ):
        reader = asyncio.StreamReader()
        for line in lines:
            reader.feed_data(json.dumps(line).encode() + b"\n")
        reader.feed_eof()
        rpc = native.Rpc(
            SimpleNamespace(stdin=SimpleNamespace(write=Mock(), drain=AsyncMock()), stdout=reader)
        )
        with pytest.raises(native.ProbeFailure, match=r"^telemetry_unavailable$"):
            await rpc.call("account/rateLimits/read", {})


async def test_native_shutdown_escalates_with_a_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    process = SimpleNamespace(
        returncode=None,
        pid=12345,
        terminate=Mock(),
        kill=Mock(),
        wait=AsyncMock(side_effect=[TimeoutError, 0]),
    )
    group = Mock()
    monkeypatch.setattr(native.os, "killpg", group, raising=False)
    await native.stop(process)
    if native.os.name == "posix":
        assert group.call_count == 2
    else:
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
    assert process.wait.await_count == 2


def test_child_drops_ambient_provider_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_HOME", "AGENTICOS_CODEX_AUTH"):
        monkeypatch.setenv(name, "fixture-ambient-secret")
    env = native.child_environment(tmp_path)
    assert env["CODEX_HOME"] == str(tmp_path)
    assert not {"OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENTICOS_CODEX_AUTH"}.intersection(env)


@pytest.mark.parametrize(
    "error,reason",
    [
        (native.ProbeFailure("provider_identity_mismatch"), "provider_identity_mismatch"),
        (TimeoutError("fixture-private-error"), "probe_timeout"),
        (OSError("fixture-private-error"), "telemetry_unavailable"),
    ],
)
async def test_entrypoint_emits_fixed_reasons_only(
    error: Exception,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CODEX_HOME", "unused-private-home")
    monkeypatch.setenv("AGENTICOS_CODEX_EXPECTED_ACCOUNT", "selected-account")
    monkeypatch.setattr(native, "collect", AsyncMock(side_effect=error))
    await native.main()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"reason_code": reason}
    assert captured.err == ""


async def test_native_start_uses_bounded_stdio_and_selected_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = SimpleNamespace(returncode=0)
    launch = AsyncMock(return_value=process)
    monkeypatch.setattr(native.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-ambient-key")
    assert await native.start("app-server", "--listen", "stdio://", home=tmp_path) is process
    args, options = launch.await_args
    assert args == ("codex", "app-server", "--listen", "stdio://")
    assert options["stdin"] == asyncio.subprocess.PIPE
    assert options["stdout"] == asyncio.subprocess.PIPE
    assert options["stderr"] == asyncio.subprocess.DEVNULL
    assert options["env"]["CODEX_HOME"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in options["env"]
    assert options["limit"] == native.MAX_BYTES


@pytest.mark.parametrize("platform", ["posix", "nt"])
async def test_shutdown_handles_exited_processes_and_both_platforms(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    group = Mock()
    monkeypatch.setattr(native, "os", SimpleNamespace(name=platform, killpg=group))
    monkeypatch.setattr(native, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    process = SimpleNamespace(
        returncode=0, pid=12345, wait=AsyncMock(), terminate=Mock(), kill=Mock()
    )
    await native.stop(process)
    process.wait.assert_not_awaited()
    process.returncode = None
    await native.stop(process)
    assert process.wait.await_count == 1
    process.wait.side_effect = [TimeoutError, 0]
    await native.stop(process)
    if platform == "posix":
        assert group.call_count == 3
    else:
        assert process.terminate.call_count == 2 and process.kill.call_count == 1


@pytest.mark.parametrize("case", ["no_input", "no_output", "eof", "oversize"])
async def test_rpc_transport_bounds_refuse_incomplete_replies(case: str) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b'{"id":1,"result":{}}\n' if case != "eof" else b"")
    reader.feed_eof()
    rpc = native.Rpc(
        SimpleNamespace(
            stdin=None if case == "no_input" else SimpleNamespace(write=Mock(), drain=AsyncMock()),
            stdout=None if case == "no_output" else reader,
        )
    )
    if case == "oversize":
        rpc.received = native.MAX_BYTES
    with pytest.raises(native.ProbeFailure, match="telemetry_unavailable"):
        await rpc.call("account/rateLimits/read", {})


@pytest.mark.parametrize(
    "page",
    [
        {"data": None},
        {"data": [{}] * 51},
        {"data": [False]},
        {"data": [], "nextCursor": "x" * 257},
        {"data": [], "nextCursor": "same-cursor"},
    ],
)
async def test_model_pagination_is_bounded_and_rejects_malformed_records(
    tmp_path: Path, page: dict[str, object]
) -> None:
    rpc = SimpleNamespace(call=AsyncMock(return_value=page))
    with pytest.raises(native.ProbeFailure, match=r"unverified|unavailable"):
        await native.read_models(rpc, tmp_path / "models_cache.json", datetime.now(UTC))
    assert rpc.call.await_count <= 4


async def test_model_page_budget_cannot_expand_without_bound(tmp_path: Path) -> None:
    rpc = SimpleNamespace(
        call=AsyncMock(side_effect=[{"data": [], "nextCursor": str(i)} for i in range(4)])
    )
    with pytest.raises(native.ProbeFailure, match="model_catalog_unverified"):
        await native.read_models(rpc, tmp_path / "models_cache.json", datetime.now(UTC))
    assert rpc.call.await_count == 4


async def test_model_pages_intersect_valid_remote_slugs_only(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = tmp_path / "models_cache.json"
    path.write_text(
        json.dumps(catalog(now, models=[{"slug": "gpt-5.4"}, {"slug": "unsafe;model"}, False])),
        encoding="utf-8",
    )
    rpc = SimpleNamespace(
        call=AsyncMock(
            side_effect=[
                {"data": [{"model": "gpt-5.4"}, {"model": "unsafe;model"}], "nextCursor": "next"},
                {"data": [{"model": "bundled-only"}], "nextCursor": None},
            ]
        )
    )
    result = await native.read_models(rpc, path, now)
    assert result["model_ids"] == ["gpt-5.4"]
    assert rpc.call.await_args.kwargs == {}
    assert rpc.call.await_args.args[1]["cursor"] == "next"


@pytest.mark.parametrize("contents", ["not-json", "x" * (native.MAX_BYTES + 1)])
async def test_bad_or_oversize_native_cache_is_unknown(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "models_cache.json"
    path.write_text(contents, encoding="utf-8")
    rpc = SimpleNamespace(call=AsyncMock(return_value={"data": [{"model": "gpt-5.4"}]}))
    result = await native.read_models(rpc, path, datetime.now(UTC))
    assert result["status"] == "unknown" and result["model_ids"] == []


async def test_missing_runtime_stdout_and_model_timeout_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = SimpleNamespace(stdout=None)
    monkeypatch.setattr(native, "start", AsyncMock(return_value=version))
    stop = AsyncMock()
    monkeypatch.setattr(native, "stop", stop)
    with pytest.raises(native.ProbeFailure, match="runtime_version_unsupported"):
        await native.collect(tmp_path, "selected-account")
    stop.assert_awaited_with(version)
    peer = Peer(tmp_path, quota())
    processes(monkeypatch, peer)
    monkeypatch.setattr(native, "read_models", AsyncMock(side_effect=TimeoutError))
    result = await native.collect(tmp_path, "selected-account")
    assert (
        result["usage"]["status"] == "available" and result["model_catalog"]["status"] == "unknown"
    )


def test_transferred_python312_entrypoint_only_runs_fake_metadata_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import ast

    path = Path(native.__file__)
    source = path.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 12))
    (tmp_path / "auth.json").write_text(
        json.dumps({"tokens": {"account_id": "selected-account"}}), encoding="utf-8"
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("AGENTICOS_CODEX_EXPECTED_ACCOUNT", "selected-account")
    commands: list[tuple[str, ...]] = []

    async def launch(*args: str, **_options: object) -> object:
        commands.append(args)
        if args == ("codex", "--version"):
            return SimpleNamespace(
                stdout=SimpleNamespace(read=AsyncMock(return_value=b"codex-cli 0.160.0\n")),
                wait=AsyncMock(),
                returncode=0,
            )
        peer = Peer(tmp_path, quota())
        peer.returncode = 0
        return peer

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    runpy.run_path(str(path), run_name="__main__")
    assert commands == [("codex", "--version"), ("codex", "app-server", "--listen", "stdio://")]
    assert json.loads(capsys.readouterr().out)["usage"]["status"] == "available"
