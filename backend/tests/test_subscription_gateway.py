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

from app.subscription_gateway import _instances
from app.subscription_gateway.__main__ import main
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
        assert (await client.get("/health")).json() == {"status": "ok"}
        refused = await client.get(
            f"/scopes/{ALICE}/accounts", headers={"Authorization": "Bearer nope"}
        )
        assert refused.status_code == 401
        assert (
            await client.get(f"/scopes/{ALICE}/accounts", headers={"Authorization": ""})
        ).status_code == 401
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
        assert (await client.get(f"/scopes/{ALICE}/logins/state-1")).json() == {"status": "ok"}
        assert (await client.get(f"/scopes/{ALICE}/logins/other")).json() == {"status": "wait"}
        callback = await client.post(
            f"/scopes/{ALICE}/logins/state-1/callback",
            json={"redirect_url": "http://localhost/cb?code=1"},
        )
        assert callback.json() == {"accepted": True}
        assert (await client.delete(f"/scopes/{ALICE}/logins/state-1")).json() == {
            "cancelled": True
        }

        accounts = (await client.get(f"/scopes/{ALICE}/accounts")).json()
        assert accounts == {
            "items": [
                {
                    "name": "antigravity-me.json",
                    "provider": "antigravity",
                    "email": "me@example.com",
                    "status": "active",
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

        assert (await client.get(f"/scopes/{ALICE}/logins/odd")).status_code == 502
        rejected = await client.post(
            f"/scopes/{ALICE}/logins/wrong/callback", json={"redirect_url": "http://localhost/cb"}
        )
        assert rejected.status_code == 400
        assert (await client.get(f"/scopes/{ALICE}/logins/bad%20state")).status_code == 400
        assert (await client.delete(f"/scopes/{ALICE}/accounts/..%2Fkeys")).status_code in {
            400,
            404,
        }
        assert (await client.delete(f"/scopes/{ALICE}/accounts/a%20b")).status_code == 400
        assert (await client.get("/scopes/not-a-scope/accounts")).status_code == 404
        assert (await client.get("/scopes/../v1/models")).status_code == 404


async def test_wipe_forgets_the_scope_for_good(supervisor: Supervisor) -> None:
    async with gateway(supervisor) as client:
        await client.get(f"/scopes/{ALICE}/v1/models")
        first_key = supervisor._running[ALICE].client_key
        assert (await client.delete(f"/scopes/{ALICE}")).json() == {"wiped": True}
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
