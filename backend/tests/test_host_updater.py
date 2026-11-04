"""Exercise the real host state machine with a Docker/Git boundary double.

No test installs a service, modifies this checkout or runs a Docker update.
"""

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from app.schemas.updates import AgentUpdateRead


@pytest.fixture(scope="module")
def host():
    path = Path(__file__).resolve().parents[2] / "deploy/updater/agent.py"
    spec = importlib.util.spec_from_file_location("agenticos_host_updater", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def instance(host, tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "backend").mkdir(parents=True)
    (app / "backend/.env").write_text(
        "SECRET_KEY=must-not-appear-in-status\nFILE_STORAGE_BACKEND=local\n"
    )
    (app / "backend/pyproject.toml").write_text('version = "1.32.0"\n')

    class Connection:
        def __init__(self, *args, **kwargs):
            self.tag = ""

        def request(self, method, path, headers):
            self.tag = path.rsplit("/", 1)[1]

        def getresponse(self):
            return self

        @property
        def status(self):
            return 200

        def read(self, limit):
            return json.dumps({"tag_name": self.tag, "draft": False, "prerelease": False}).encode()

        def close(self):
            pass

    class Commands(host.Commands):
        def __init__(self):
            self.calls = []
            self.head = "a" * 40
            self.fail = None
            self.workers = ["local-worker"]
            self.healthy = True

        def run(self, args, *, cwd, env=None, output=None, timeout=1200, user=None, group=None):
            self.calls.append(tuple(args))
            if self.fail and self.fail(args):
                raise host.Refused("command_failed")
            if output is not None:
                output.write(b"PGDMP-test-backup")
                return ""
            if args[0] == "git":
                if "status" in args:
                    return ""
                if "HEAD" in args:
                    return self.head
                if "rev-parse" in args:
                    return "b" * 40
                if "worktree" in args:
                    checkout = Path(args[-2])
                    (checkout / "backend").mkdir(parents=True)
                    (checkout / "docker-compose-prod.updater.yml").write_text("services: {}")
                if "checkout" in args:
                    self.head = args[-1]
                return ""
            if args[1:3] == ["image", "inspect"]:
                return args[-1].split(":")[0] + "@sha256:" + "f" * 64
            if args[1] == "cp":
                Path(args[-1]).mkdir()
                return ""
            if args[1] == "inspect":
                return (
                    "local-worker"
                    if "{{.Config.Hostname}}" in args
                    else "healthy"
                    if self.healthy
                    else "unhealthy"
                )
            if "{{.Server.Version}}" in args:
                return "28.0.0"
            if "version" in args and "--short" in args:
                return "2.39.0"
            if "config" in args:
                frontend = "agenticos-frontend" in args
                tag = (env or {}).get("AGENTICOS_VERSION", "1.32.0")
                services = (
                    {"frontend": {"image": f"ghcr.io/vstorm-co/agenticos-frontend:{tag}"}}
                    if frontend
                    else {
                        "app": {"image": f"ghcr.io/vstorm-co/agenticos-backend:{tag}"},
                        "worker": {"image": f"ghcr.io/vstorm-co/agenticos-backend:{tag}"},
                        "migrate": {"image": f"ghcr.io/vstorm-co/agenticos-backend:{tag}"},
                        "db": {"image": "postgres:16"},
                        "browser": {"image": "optional:1", "profiles": ["browser"]},
                    }
                )
                return json.dumps({"services": services})
            if "ps" in args:
                return "c" * 64
            if any("background_workers" in item for item in args):
                return json.dumps(self.workers)
            if any("pg_database_size" in item for item in args):
                return "4096"
            if "du" in args:
                return "1024 /app/media"
            if any("SELECT (SELECT count" in item for item in args):
                return "0"
            return ""

    monkeypatch.setattr(host, "HTTPSConnection", Connection)
    config = host.Config(
        app,
        tmp_path / "state",
        tmp_path / "runtime",
        "agenticos",
        proxy="nginx",
        api_gid=os.getgid(),
    )
    commands = Commands()
    updater = host.Updater(config, commands)
    monkeypatch.setattr(updater.stop, "wait", lambda seconds: False)
    return updater, commands


def test_prepare_pins_images_backs_up_and_does_not_deploy(host, instance):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    state = AgentUpdateRead.model_validate(updater.status())
    assert state.operation.phase == "ready"
    assert state.operation.commit == "b" * 40
    assert all("@sha256:" in image for image in state.operation.images.values())
    assert state.operation.backup_id.endswith("/prepared")
    assert "must-not-appear" not in json.dumps(updater.status())
    assert not any("up" in call or "checkout" in call for call in commands.calls)
    assert any("refs/agenticos-updater/main" in call for call in commands.calls)
    assert all("optional:1" not in call for call in commands.calls)
    reloaded = host.Updater(updater.config, commands)
    assert reloaded.operation.phase == "ready"


def test_update_drains_then_refreshes_backup_before_migration_and_health_checks(host, instance):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    identifier = updater.operation.id
    updater.apply(identifier, None)
    updater.tick()
    assert updater.operation.phase == "succeeded"
    assert updater.operation.backup_id.endswith("/final")
    assert json.loads((updater.config.runtime_dir / "control.json").read_text()) == {
        "draining": False
    }
    stop = next(i for i, call in enumerate(commands.calls) if "stop" in call)
    final_backup = next(
        i
        for i, call in enumerate(commands.calls[stop:], stop)
        if any("pg_dump" in item for item in call)
    )
    migrate = next(
        i for i, call in enumerate(commands.calls) if "run" in call and "migrate" in call
    )
    deploy = next(i for i, call in enumerate(commands.calls) if "up" in call)
    assert stop < final_backup < migrate < deploy
    assert "AGENTICOS_VERSION=1.33.0" in (updater.config.app_dir / "backend/.env").read_text()
    assert (
        updater.config.app_dir.stat().st_uid
        == (updater.config.app_dir / "backend/.env").stat().st_uid
    )


def test_schedule_and_cancel_survive_a_restart_without_starting_deployment(host, instance):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    updater.apply(updater.operation.id, host.time.time() + 3600)
    reloaded = host.Updater(updater.config, commands)
    reloaded.tick()
    assert reloaded.operation.phase == "scheduled"
    reloaded.cancel(reloaded.operation.id)
    assert reloaded.operation.phase == "cancelled"
    assert not any("up" in call for call in commands.calls)


@pytest.mark.parametrize("phase", ["migrate", "health"])
def test_failure_after_migration_stays_closed_and_prevents_another_update(host, instance, phase):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    if phase == "migrate":
        commands.fail = lambda args: "migrate" in args and "run" in args
    else:
        commands.healthy = False
    updater.apply(updater.operation.id, None)
    updater.tick()
    assert updater.operation.phase == "failed"
    assert json.loads((updater.config.runtime_dir / "control.json").read_text())["draining"] is True
    with pytest.raises(host.Refused, match="manual_recovery_required"):
        updater.prepare("1.34.0")


def test_backup_failure_before_migration_restarts_the_existing_services(host, instance):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    commands.fail = lambda args: any("pg_dump" in item for item in args)
    updater.apply(updater.operation.id, None)
    updater.tick()
    assert updater.operation.phase == "failed"
    assert commands.head == "a" * 40
    assert any("start" in call and "app" in call and "worker" in call for call in commands.calls)
    assert (
        json.loads((updater.config.runtime_dir / "control.json").read_text())["draining"] is False
    )


def test_remote_workers_require_a_pipeline_and_versions_cannot_be_commands(host, instance):
    updater, commands = instance
    for value in ["main", "1.33.0;touch /tmp/evil", "../1.33.0", "2.0.0", "1.33.0-beta"]:
        with pytest.raises(host.Refused):
            updater.prepare(value)
    assert commands.calls == []
    commands.workers.append("another-server")
    updater.prepare("1.33.0")
    updater.tick()
    assert updater.operation.phase == "failed"
    assert updater.operation.reason == "multi_host_requires_pipeline"


def test_restart_restores_maintenance_even_when_runtime_directory_was_lost(host, instance):
    updater, commands = instance
    updater.prepare("1.33.0")
    updater.tick()
    updater.drain(on=True)
    updater.update("applying")
    (updater.config.runtime_dir / "control.json").unlink()
    recovered = host.Updater(updater.config, commands)
    assert recovered.operation.phase == "failed"
    assert recovered.operation.reason == "interrupted"
    assert json.loads((updater.config.runtime_dir / "control.json").read_text())["draining"]
    with pytest.raises(host.Refused, match="manual_recovery_required"):
        recovered.prepare("1.34.0")
    (updater.config.runtime_dir / "control.json").unlink()
    host.Updater(updater.config, commands)
    assert json.loads((updater.config.runtime_dir / "control.json").read_text())["draining"]


@pytest.fixture
def socket_path():
    # macOS limits Unix socket paths to 104 bytes; pytest test names exceed it.
    with tempfile.TemporaryDirectory(prefix="aos-", dir="/tmp") as directory:
        yield Path(directory) / "agent.sock"


def test_unix_protocol_rejects_extra_fields_before_auditing_and_preserves_actor(
    host, instance, socket_path
):
    import threading

    import httpx

    updater, _ = instance
    socket = socket_path
    with host.UnixHTTPServer(str(socket), host.Handler) as server:
        server.updater = updater
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket)), timeout=2) as client:
                payload = {"actor_id": "a" * 32, "version": "1.33.0", "secret": "never-audit"}
                assert client.post("http://updater/v1/prepare", json=payload).status_code == 409
                assert not (updater.config.state_dir / "audit.jsonl").exists()
                del payload["secret"]
                response = client.post("http://updater/v1/prepare", json=payload)
                assert response.status_code == 202
                assert response.json()["operation"]["phase"] == "preparing"
                assert client.get("http://updater/v1/status").json() == response.json()
                assert client.get("http://updater/elsewhere").status_code == 404
                assert (
                    client.post("http://updater/v1/apply", json={"actor_id": "bad"}).status_code
                    == 409
                )
                assert (
                    client.post("http://updater/v1/apply", content=b"x" * 5000).status_code == 409
                )
            audit = (updater.config.state_dir / "audit.jsonl").read_text()
            assert "never-audit" not in audit
            assert json.loads(audit)["parameters"] == {"version": "1.33.0"}
        finally:
            server.shutdown()
            thread.join()


def test_proxy_choice_is_explicit_and_preserves_traefik_overlays(host, instance):
    from dataclasses import replace

    updater, commands = instance
    compose = host.Compose(replace(updater.config, proxy="traefik"), commands)
    assert any(arg.endswith("docker-compose-prod.traefik.yml") for arg in compose.args())
    assert any(
        arg.endswith("docker-compose-prod.frontend.traefik.yml")
        for arg in compose.args(frontend=True)
    )
    with pytest.raises(host.Refused, match="unsupported_configuration"):
        host.Compose(replace(updater.config, proxy=""), commands).args()


def test_sandbox_compose_receives_the_host_docker_socket_group(host, instance, monkeypatch):
    from types import SimpleNamespace

    updater, _ = instance
    (updater.config.app_dir / "backend/.env").write_text("SANDBOXD_TOKEN=local-test\n")
    monkeypatch.delenv("DOCKER_GID", raising=False)
    original = Path.stat

    def stat(path, *args, **kwargs):
        return (
            SimpleNamespace(st_gid=998)
            if str(path) == "/var/run/docker.sock"
            else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "stat", stat)
    assert updater.compose.env()["DOCKER_GID"] == "998"
    monkeypatch.setenv("DOCKER_GID", "123")
    assert updater.compose.env()["DOCKER_GID"] == "123"
    monkeypatch.setenv("DOCKER_GID", "invalid")
    with pytest.raises(host.Refused, match="unsupported_configuration"):
        updater.compose.env()


def test_stale_dependency_health_is_retried_once_but_other_failures_are_not(
    host, instance, monkeypatch
):
    updater, _ = instance
    attempts = []

    def run(*args, **kwargs):
        attempts.append(args)
        if len(attempts) == 1:
            raise host.Refused("stale_health")
        return ""

    monkeypatch.setattr(updater.compose, "run", run)
    updater.start_services(frontend=False, override=Path("pin.json"), release="1.33.0")
    assert len(attempts) == 2

    def fail(*args, **kwargs):
        attempts.append(args)
        raise host.Refused("command_failed")

    monkeypatch.setattr(updater.compose, "run", fail)
    with pytest.raises(host.Refused, match="command_failed"):
        updater.start_services(frontend=False, override=Path("pin.json"), release="1.33.0")
    assert len(attempts) == 3


def test_drain_counts_only_live_heartbeats_and_unexpired_leases(host, instance):
    updater, commands = instance
    assert updater.active_work() == 0
    query = commands.calls[-1][-1]
    assert "COALESCE(GREATEST(heartbeat_at, updated_at, started_at), created_at)" in query
    assert "make_interval(secs => 120.0)" in query
    assert "modality != 'voice'" in query
    assert "lease_until >= now()" in query
    assert "heartbeat_at >= now() - interval '45 seconds'" in query


def test_runtime_directory_is_preserved_across_service_restarts():
    source = (Path(__file__).resolve().parents[2] / "deploy/updater/install.py").read_text()
    assert "RuntimeDirectoryPreserve=yes" in source


@pytest.mark.parametrize(
    "message,expected",
    [(b"container db is unhealthy", "stale_health"), (b"permission denied", "command_failed")],
)
def test_commands_classifies_only_compose_health_failures(
    host, tmp_path, monkeypatch, message, expected
):
    import subprocess

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=message)

    monkeypatch.setattr(host.subprocess, "run", fail)
    with pytest.raises(host.Refused, match=expected):
        host.Commands().run(["docker", "compose", "up", "-d"], cwd=tmp_path)
    with pytest.raises(host.Refused, match="command_failed"):
        host.Commands().run(["git", "status"], cwd=tmp_path)


@pytest.mark.parametrize("stopped", [False, True])
def test_stale_health_retry_is_bounded_and_interruptible(host, instance, monkeypatch, stopped):
    updater, _ = instance
    from unittest.mock import Mock

    run = Mock(side_effect=host.Refused("stale_health"))
    monkeypatch.setattr(updater.compose, "run", run)
    monkeypatch.setattr(updater.stop, "wait", lambda seconds: stopped)
    with pytest.raises(host.Refused, match="interrupted" if stopped else "stale_health"):
        updater.start_services(frontend=True, override=Path("pin.json"), release="1.33.0")
    assert run.call_count == (1 if stopped else 2)
