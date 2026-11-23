"""The subscription gateway: one CLIProxyAPI process per scope, reached only through the supervisor.

The end-to-end tests run a stand-in CLIProxyAPI (`subscription_gateway_fake.py`)
as a real child process, so spawning, probing, key handling and streaming are
exercised the way the container runs them.
"""

import asyncio
import json
import stat
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import yaml
from pydantic import JsonValue

from app.subscription_gateway import _instances, _server
from app.subscription_gateway.__main__ import main
from app.subscription_gateway._account_data import account_prefix
from app.subscription_gateway._instances import GatewayError, Supervisor
from app.subscription_gateway._server import create_app

pytestmark = pytest.mark.anyio

TOKEN = "t" * 40
ALICE = "a" * 64
BOB = "b" * 64
FAKE = Path(__file__).with_name("subscription_gateway_fake.py")


def fake_binary(folder: Path) -> str:
    """An executable that behaves like `cliproxyapi --config <path>`."""
    binary = folder / "cliproxyapi"
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    binary.chmod(0o700)
    return str(binary)


async def sleeper(_binary: str, _config: Path) -> asyncio.subprocess.Process:
    """A process that runs but never serves anything."""
    return await asyncio.create_subprocess_exec("sleep", "30")


async def always(_port: int, _key: str) -> bool:
    return True


async def never(_port: int, _key: str) -> bool:
    return False


@asynccontextmanager
async def gateway(supervisor: Supervisor) -> AsyncGenerator[httpx.AsyncClient]:
    app = create_app(supervisor, TOKEN, reap_seconds=0.05)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://gateway",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client,
    ):
        yield client


@pytest.fixture
def supervisor(tmp_path: Path) -> Supervisor:
    return Supervisor(root=tmp_path / "data", binary=fake_binary(tmp_path), start_timeout=15)


async def test_every_route_needs_the_shared_token(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        reply = await client.get("/health")
        assert reply.json() == {"status": "ok"}
        refused = await client.get(
            f"/scopes/{ALICE}/accounts", headers={"Authorization": "Bearer nope"}
        )
        assert refused.status_code == 401
        reply = await client.get(f"/scopes/{ALICE}/accounts", headers={"Authorization": ""})
        assert reply.status_code == 401
    assert not supervisor.root.exists()


async def test_model_traffic_uses_the_scopes_own_private_key(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        models = await client.get(f"/scopes/{ALICE}/v1/models")
        assert models.status_code == 200
        assert models.json()["data"][0]["id"] == "gemini-test"

        async with client.stream(
            "POST",
            f"/scopes/{ALICE}/v1/chat/completions",
            json={"model": "gemini-test", "stream": True},
        ) as answer:
            body = "".join([chunk async for chunk in answer.aiter_text()])
        assert answer.headers["content-type"].startswith("text/event-stream")
        assert "Hello" in body and "[DONE]" in body

    folder = supervisor.root / ALICE
    keys = json.loads((folder / "keys.json").read_text())
    config = yaml.safe_load((folder / "config.yaml").read_text())
    assert config["access"]["api-keys"] == [keys["client"]]
    assert config["management"]["secret-key"] == keys["management"]
    assert config["server"]["host"] == "127.0.0.1"
    assert TOKEN not in (folder / "config.yaml").read_text()
    for private in (folder, folder / "auths"):
        assert stat.S_IMODE(private.stat().st_mode) == 0o700
    for secret in (folder / "keys.json", folder / "config.yaml"):
        assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    assert supervisor._running == {}


async def test_two_scopes_never_share_a_process_or_keys(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        alice = (await client.get(f"/scopes/{ALICE}/v1/models")).json()["data"][0]["port"]
        bob = (await client.get(f"/scopes/{BOB}/v1/models")).json()["data"][0]["port"]
        assert alice != bob
        assert supervisor._running[ALICE].client_key != supervisor._running[BOB].client_key
        assert supervisor._running[ALICE].management_key != supervisor._running[BOB].management_key


async def test_compressed_model_responses_remain_decodable(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        response = await client.post(
            f"/scopes/{ALICE}/v1/chat/completions",
            json={"model": "compressed-test", "stream": True},
        )
        assert response.headers["content-encoding"] == "gzip"
        assert '"text":"Cześć"' in response.text
        assert "[DONE]" in response.text


async def test_sign_in_answers_carry_only_what_the_console_needs(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        started = await client.post(f"/scopes/{ALICE}/logins", json={"provider": "antigravity"})
        assert started.json() == {
            "url": "https://login.example/antigravity",
            "state": "state-1",
            "flow": "device",
            "user_code": "CODE-1",
        }
        reply = await client.get(f"/scopes/{ALICE}/logins/state-1")
        assert reply.json() == {"status": "ok"}
        reply = await client.get(f"/scopes/{ALICE}/logins/other")
        assert reply.json() == {"status": "wait"}
        callback = await client.post(
            f"/scopes/{ALICE}/logins/state-1/callback",
            json={"redirect_url": "http://localhost/cb?code=1"},
        )
        assert callback.json() == {"accepted": True}
        reply = await client.delete(f"/scopes/{ALICE}/logins/state-1")
        assert reply.json() == {"cancelled": True}

        accounts = (await client.get(f"/scopes/{ALICE}/accounts")).json()
        assert accounts == {
            "items": [
                {
                    "name": "antigravity-me.json",
                    "provider": "antigravity",
                    "email": "me@example.com",
                    "status": "active",
                    "model_prefix": account_prefix(ALICE, "antigravity-me.json"),
                    "usage": {"status": "unavailable", "observed_at": None, "windows": []},
                }
            ]
        }
        removed = await client.delete(f"/scopes/{ALICE}/accounts/antigravity-me.json")
        assert removed.json() == {"removed": True}


async def test_refusals_stay_generic(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        unsupported = await client.post(f"/scopes/{ALICE}/logins", json={"provider": "cursor"})
        assert unsupported.status_code == 400
        upstream_failure = await client.post(f"/scopes/{ALICE}/logins", json={"provider": "broken"})
        assert upstream_failure.status_code == 400  # not in PROVIDERS, never reaches the process

        with patch("app.subscription_gateway._server.PROVIDERS", frozenset({"broken", "xai"})):
            crashed = await client.post(f"/scopes/{ALICE}/logins", json={"provider": "broken"})
            assert crashed.status_code == 502
            assert "boom" not in crashed.text
            malformed = await client.post(f"/scopes/{ALICE}/logins", json={"provider": "xai"})
            assert malformed.status_code == 502

        reply = await client.get(f"/scopes/{ALICE}/logins/odd")
        assert reply.status_code == 502
        rejected = await client.post(
            f"/scopes/{ALICE}/logins/wrong/callback", json={"redirect_url": "http://localhost/cb"}
        )
        assert rejected.status_code == 400
        reply = await client.get(f"/scopes/{ALICE}/logins/bad%20state")
        assert reply.status_code == 400
        reply = await client.delete(f"/scopes/{ALICE}/accounts/..%2Fkeys")
        assert reply.status_code in {
            400,
            404,
        }
        reply = await client.delete(f"/scopes/{ALICE}/accounts/a%20b")
        assert reply.status_code == 400
        reply = await client.get("/scopes/not-a-scope/accounts")
        assert reply.status_code == 404
        reply = await client.get("/scopes/../v1/models")
        assert reply.status_code == 404


async def test_wipe_forgets_the_scope_for_good(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        await client.get(f"/scopes/{ALICE}/v1/models")
        first_key = supervisor._running[ALICE].client_key
        reply = await client.delete(f"/scopes/{ALICE}")
        assert reply.json() == {"wiped": True}
        assert ALICE not in supervisor._running
        assert not (supervisor.root / ALICE).exists()
        await client.get(f"/scopes/{ALICE}/v1/models")
        assert supervisor._running[ALICE].client_key != first_key


async def test_keys_survive_a_restart(supervisor: Supervisor) -> None:
    async with supervisor.use(ALICE) as first:
        key = first.client_key
    await supervisor.stop(ALICE)
    async with supervisor.use(ALICE) as again:
        assert again.client_key == key
        assert again.process is not first.process
    await supervisor.close()
    await supervisor.stop(BOB)  # nothing running is nothing to stop


async def test_an_unreachable_process_is_a_502(tmp_path: Path) -> None:
    supervisor = Supervisor(root=tmp_path, binary="unused", spawn=sleeper, probe=always)
    async with gateway(supervisor) as client:
        answer = await client.post(f"/scopes/{ALICE}/v1/chat/completions", json={})
        assert answer.status_code == 502
        assert supervisor._running[ALICE].active == 0


async def test_a_process_that_never_answers_is_stopped(tmp_path: Path) -> None:
    supervisor = Supervisor(
        root=tmp_path, binary="unused", spawn=sleeper, probe=never, start_timeout=0.3
    )
    with pytest.raises(GatewayError) as refused:
        await supervisor._ensure(ALICE)
    assert refused.value.status == 503
    assert supervisor._running == {}


async def test_a_dead_process_is_replaced_and_reaped(tmp_path: Path) -> None:
    supervisor = Supervisor(root=tmp_path, binary="unused", spawn=sleeper, probe=always)
    first = await supervisor._ensure(ALICE)
    first.process.kill()
    await first.process.wait()
    second = await supervisor._ensure(ALICE)
    assert second is not first

    second.process.kill()
    await second.process.wait()
    await supervisor.reap()
    assert supervisor._running == {}


async def test_idle_processes_are_reaped_but_busy_ones_are_not(tmp_path: Path) -> None:
    now = [0.0]
    supervisor = Supervisor(
        root=tmp_path,
        binary="unused",
        spawn=sleeper,
        probe=always,
        idle_seconds=10,
        clock=lambda: now[0],
    )
    async with supervisor.use(ALICE):
        await supervisor._ensure(BOB)
        now[0] = 100
        await supervisor.reap()
        assert set(supervisor._running) == {ALICE}
    now[0] = 200
    await supervisor.reap()
    assert supervisor._running == {}


async def test_the_ceiling_evicts_the_least_recently_used_idle_scope(tmp_path: Path) -> None:
    now = [0.0]
    supervisor = Supervisor(
        root=tmp_path,
        binary="unused",
        spawn=sleeper,
        probe=always,
        max_instances=2,
        clock=lambda: now[0],
    )
    async with supervisor.use(ALICE):
        pass
    now[0] = 5
    async with supervisor.use(BOB):
        await supervisor._ensure("c" * 64)
        assert set(supervisor._running) == {BOB, "c" * 64}
        async with supervisor.use("c" * 64):
            with pytest.raises(GatewayError) as busy:
                await supervisor._ensure("d" * 64)
    assert busy.value.status == 503
    await supervisor.close()


async def test_a_process_ignoring_terminate_is_killed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stubborn(_binary: str, _config: Path) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec("sh", "-c", 'trap "" TERM; sleep 30 & wait')
        await asyncio.sleep(0.2)
        return process

    monkeypatch.setattr(_instances, "STOP_GRACE_SECONDS", 0.2)
    supervisor = Supervisor(root=tmp_path, binary="unused", spawn=stubborn, probe=always)
    instance = await supervisor._ensure(ALICE)
    await supervisor.stop(ALICE)
    assert instance.process.returncode is not None


async def test_the_reaper_runs_in_the_background(tmp_path: Path) -> None:
    supervisor = Supervisor(
        root=tmp_path, binary="unused", spawn=sleeper, probe=always, idle_seconds=0
    )
    async with gateway(supervisor):
        await supervisor._ensure(ALICE)
        for _ in range(50):
            if not supervisor._running:
                break
            await asyncio.sleep(0.05)
        assert supervisor._running == {}


def test_main_requires_a_long_token(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main({"SUBSCRIPTION_GATEWAY_TOKEN": "short"})

    with patch("app.subscription_gateway.__main__.uvicorn.run") as run:
        main(
            {
                "SUBSCRIPTION_GATEWAY_TOKEN": TOKEN,
                "SUBSCRIPTION_GATEWAY_DATA": str(tmp_path / "data"),
                "SUBSCRIPTION_GATEWAY_MAX_PROCESSES": "3",
            }
        )
    assert stat.S_IMODE((tmp_path / "data").stat().st_mode) == 0o700
    assert run.call_args.kwargs == {"host": "0.0.0.0", "port": 8400}


async def test_account_models_are_read_from_the_scopes_management_api(
    supervisor: Supervisor,
) -> None:
    async with gateway(supervisor) as client:
        answer = await client.get(f"/scopes/{ALICE}/accounts/antigravity-me.json/models")
        assert answer.status_code == 200
        assert answer.json() == {"items": [{"id": "claude-via-google"}]}
        malformed = await client.get(f"/scopes/{ALICE}/accounts/unknown.json/models")
        assert malformed.status_code == 502
        bad = await client.get(f"/scopes/{ALICE}/accounts/bad!name/models")
        assert bad.status_code == 400


async def test_a_chosen_account_gets_a_scope_bound_model_route(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:

        async def select(scope: str, model: str = "claude-via-google") -> httpx.Response:
            return await client.post(
                f"/scopes/{scope}/accounts/antigravity-me.json/model-selection",
                json={"model": model},
            )

        alice = await select(ALICE)
        bob = await select(BOB)
        assert alice.status_code == bob.status_code == 200
        expected = account_prefix(ALICE, "antigravity-me.json") + "/claude-via-google"
        assert alice.json() == {"model": expected}
        assert bob.json() != alice.json()
        reply = await select(ALICE)
        assert reply.json() == alice.json()
        reply = await select(ALICE, "unlisted")
        assert reply.status_code == 400
        streamed = await client.post(
            f"/scopes/{ALICE}/v1/chat/completions", json={"model": expected}
        )
        assert expected in streamed.text
        missing = await client.post(
            f"/scopes/{ALICE}/accounts/missing.json/model-selection",
            json={"model": "claude-via-google"},
        )
        assert missing.status_code == 404


async def test_account_selection_refuses_unusable_or_unregistered_routes(
    supervisor: Supervisor, monkeypatch: pytest.MonkeyPatch
) -> None:
    mode = "disabled"

    async def management(
        _instance: _instances.Instance, _method: str, path: str, **_kwargs: object
    ) -> JsonValue:
        if path == "/credentials":
            if mode == "malformed":
                return {"files": "bad"}
            return {"files": [{"name": "account.json", "disabled": mode == "disabled"}]}
        if path == "/credentials/models":
            return {"models": [{"id": "known"}]}
        return {}

    monkeypatch.setattr(_server, "_management", management)
    async with gateway(supervisor) as client:

        async def select() -> httpx.Response:
            return await client.post(
                f"/scopes/{ALICE}/accounts/account.json/model-selection", json={"model": "known"}
            )

        reply = await select()
        assert reply.status_code == 409
        mode = "malformed"
        reply = await select()
        assert reply.status_code == 502
        mode = "not-registered"
        reply = await select()
        assert reply.status_code == 503
    with pytest.raises(GatewayError):
        _server._public_account(ALICE, {"name": None})
    assert _server._model_ids({"models": [None, {"id": 1}, {"id": "ok"}]}) == ["ok"]
    with pytest.raises(GatewayError):
        _server._model_ids([])


async def test_account_quota_route_uses_only_the_named_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.subscription_gateway.contracts import AccountUsage

    supervisor = Supervisor(tmp_path, "unused", spawn=sleeper, probe=always)
    row: dict[str, JsonValue] = {"name": "a.json", "provider": "antigravity", "auth_index": "mine"}

    async def management(
        _instance: _instances.Instance, _method: str, _path: str, **_kwargs: object
    ) -> JsonValue:
        return {"files": [row]}

    monkeypatch.setattr(_server, "_management", management)
    quota = AsyncMock(return_value=AccountUsage())
    monkeypatch.setattr(_server, "antigravity_usage", quota)
    monkeypatch.setattr(_server, "codex_usage", quota)
    monkeypatch.setattr(_server, "claude_usage", quota)
    monkeypatch.setattr(_server, "kimi_usage", quota)
    async with gateway(supervisor) as client:
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.status_code == 200
        assert quota.await_args.args[0].scope == ALICE
        assert quota.await_args.args[1] == "mine"
        row.pop("auth_index")
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.status_code == 409
        row["provider"] = "codex"
        row["auth_index"] = "mine"
        row["id_token"] = {"chatgpt_account_id": "account"}
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.status_code == 200
        assert quota.await_args.args[2] == "account"
        row["id_token"] = None
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.json()["status"] == "unavailable"
        row["provider"] = "claude"
        calls = quota.await_count
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.json()["status"] == "unavailable"
        assert quota.await_count == calls + 1
        row.pop("auth_index")
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.status_code == 409
        row["auth_index"] = "mine"
        for provider in ("kimi", "kimi-ai"):
            row["provider"] = provider
            reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
            assert reply.status_code == 200
            assert quota.await_args.kwargs == {"international": provider == "kimi-ai"}
        row.pop("auth_index")
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.status_code == 409
        row["provider"] = "meta"
        reply = await client.get(f"/scopes/{ALICE}/accounts/a.json/usage")
        assert reply.json()["status"] == "unavailable"
        reply = await client.get(f"/scopes/{ALICE}/accounts/missing.json/usage")
        assert reply.status_code == 404


@pytest.mark.parametrize("provider", sorted(_server.PROVIDERS))
async def test_every_subscription_signin_uses_the_selected_provider_and_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    supervisor = Supervisor(tmp_path, "unused", spawn=sleeper, probe=always)
    calls: list[tuple[str, str, str, dict[str, object]]] = []

    async def management(
        instance: _instances.Instance, method: str, path: str, **kwargs: object
    ) -> JsonValue:
        calls.append((instance.scope, method, path, kwargs))
        return {
            "url": "https://signin.example/device",
            "state": "state",
            "flow": "device" if provider in {"kimi", "kimi-ai", "xai", "meta"} else "browser",
            "access_token": "private-token",
        }

    monkeypatch.setattr(_server, "_management", management)
    async with gateway(supervisor) as client:
        response = await client.post(f"/scopes/{ALICE}/logins", json={"provider": provider})
    assert response.status_code == 200
    assert calls == [(ALICE, "GET", "/oauth/auth-url", {"params": {"provider": provider}})]
    assert "private-token" not in response.text


@pytest.mark.parametrize("timeout", [False, True])
async def test_management_transport_failures_are_controlled_and_private(
    monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    from unittest.mock import MagicMock

    async def send(request: httpx.Request) -> httpx.Response:
        error = httpx.ReadTimeout if timeout else httpx.ConnectError
        raise error("private-token", request=request)

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        _server.httpx,
        "AsyncClient",
        lambda **_kwargs: client_class(transport=httpx.MockTransport(send)),
    )
    instance = _instances.Instance(
        ALICE, 1234, "client", "management", MagicMock(spec=asyncio.subprocess.Process), 0
    )
    with pytest.raises(GatewayError) as error:
        await _server._management(instance, "GET", "/oauth/status")
    assert error.value.status == (504 if timeout else 502)
    assert "private-token" not in str(error.value)


@pytest.mark.parametrize("failure", ["cancel", "probe"])
async def test_startup_failure_reaps_the_untracked_child(tmp_path: Path, failure: str) -> None:
    entered = asyncio.Event()
    child: asyncio.subprocess.Process | None = None

    async def spawn(binary: str, config: Path) -> asyncio.subprocess.Process:
        nonlocal child
        child = await sleeper(binary, config)
        return child

    async def probe(_port: int, _key: str) -> bool:
        entered.set()
        if failure == "probe":
            raise RuntimeError("probe failed")
        await asyncio.Event().wait()
        return False

    supervisor = Supervisor(root=tmp_path, binary="unused", spawn=spawn, probe=probe)

    async def use() -> None:
        async with supervisor.use(ALICE):
            pytest.fail("A failed startup must not be admitted")

    task = asyncio.create_task(use())
    await entered.wait()
    if failure == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
        await task
    await supervisor.close()
    assert child is not None and child.returncode is not None
    assert supervisor._running == {}


@pytest.mark.parametrize("send_fails", [False, True])
async def test_forwarded_response_releases_its_lease_on_stream_or_send_failure(
    tmp_path: Path, send_fails: bool
) -> None:
    import contextlib

    from starlette.types import Message

    class BrokenStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncGenerator[bytes]:
            yield b"first"
            raise httpx.ReadError("upstream broke")

        async def aclose(self) -> None:
            self.closed = True

    supervisor = Supervisor(root=tmp_path, binary="unused", spawn=sleeper, probe=always)
    held = contextlib.AsyncExitStack()
    instance = await held.enter_async_context(supervisor.use(ALICE))
    stream = BrokenStream()
    upstream = httpx.Response(200, stream=stream)
    held.push_async_callback(upstream.aclose)
    response = _server._ForwardedResponse(upstream, held)

    async def send(_message: Message) -> None:
        if send_fails:
            raise RuntimeError("downstream broke")

    async def receive() -> Message:
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    try:
        with pytest.raises(RuntimeError if send_fails else httpx.ReadError):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert instance.active == 0 and stream.closed
    finally:
        await held.aclose()
        await supervisor.close()


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError])
async def test_wipe_reports_filesystem_failure_and_only_ignores_absence(
    supervisor: Supervisor, monkeypatch: pytest.MonkeyPatch, error: type[OSError]
) -> None:
    await supervisor.wipe(ALICE)
    async with supervisor.use(ALICE):
        pass

    def denied(_path: Path) -> None:
        raise error("private path")

    monkeypatch.setattr(_instances.shutil, "rmtree", denied)
    with pytest.raises(GatewayError, match=r"deletion (failed|is incomplete)") as failed:
        await supervisor.wipe(ALICE)
    assert failed.value.status == 503
    assert (supervisor.root / ALICE / "keys.json").exists()
    assert ALICE not in supervisor._running


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_failure_before_returning_the_stream_closes_every_acquired_resource(
    supervisor: Supervisor, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    from contextlib import AsyncExitStack

    upstreams: list[httpx.Response] = []

    def failed_response(
        upstream: httpx.Response, _held: AsyncExitStack
    ) -> _server._ForwardedResponse:
        upstreams.append(upstream)
        raise failure("response admission interrupted")

    async with gateway(supervisor) as client:
        monkeypatch.setattr(_server, "_ForwardedResponse", failed_response)
        with pytest.raises(failure):
            await client.get(f"/scopes/{ALICE}/v1/models")
        assert supervisor._running[ALICE].active == 0
        assert upstreams[0].is_closed
