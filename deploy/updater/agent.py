"""Host-owned Compose updater. Python 3.12+, Unix socket only, no third-party deps.

Installed outside the application checkout so recreating the API cannot interrupt
an update. Only published stable AgenticOS tags on main are accepted; requests
cannot supply paths, image references, repository URLs or shell commands.
"""

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import signal
import socketserver
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from http.client import HTTPException, HTTPSConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import BinaryIO, Literal, Self

type Phase = Literal[
    "preparing",
    "ready",
    "scheduled",
    "draining",
    "backing_up",
    "applying",
    "checking",
    "succeeded",
    "failed",
    "cancelled",
]
PHASES: tuple[Phase, ...] = (
    "preparing",
    "ready",
    "scheduled",
    "draining",
    "backing_up",
    "applying",
    "checking",
    "succeeded",
    "failed",
    "cancelled",
)
FINAL = {"succeeded", "failed", "cancelled"}
REPO = "https://github.com/vstorm-co/agenticos.git"
RELEASES = "/repos/vstorm-co/agenticos/releases/tags/"
VERSION = re.compile(r"^1\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")
ID = re.compile(r"^[a-f0-9]{32}$")


class Refused(Exception):
    """A closed operational reason, never raw command output or environment data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def json_object(raw: bytes) -> dict[str, object]:
    value: object = json.loads(raw)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise Refused("invalid_payload")
    return {str(key): item for key, item in value.items()}


def text(value: object) -> str:
    if not isinstance(value, str):
        raise Refused("invalid_payload")
    return value


def number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise Refused("invalid_payload")
    return float(value)


def version(value: object) -> str:
    result = text(value)
    if not VERSION.fullmatch(result):
        raise Refused("invalid_version")
    return result


def atomic_json(path: Path, value: object, *, gid: int | None = None) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        temporary.chmod(0o640 if gid is not None else 0o600)
        if gid is not None:
            os.chown(temporary, -1, gid)
        json.dump(value, stream, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@dataclass
class Operation:
    id: str
    version: str
    phase: Phase
    created_at: float
    updated_at: float
    scheduled_for: float | None = None
    commit: str = ""
    previous_commit: str = ""
    reason: str | None = None
    backup_id: str | None = None
    images: dict[str, str] = field(default_factory=dict)
    requires_recovery: bool = False

    @classmethod
    def parse(cls, value: dict[str, object]) -> Self:
        phase = next((item for item in PHASES if item == value.get("phase")), None)
        identifier = text(value.get("id"))
        images = value.get("images", {})
        if phase is None or not ID.fullmatch(identifier) or not isinstance(images, dict):
            raise Refused("invalid_state")
        return cls(
            id=identifier,
            version=version(value.get("version")),
            phase=phase,
            created_at=number(value.get("created_at")),
            updated_at=number(value.get("updated_at")),
            scheduled_for=None
            if value.get("scheduled_for") is None
            else number(value["scheduled_for"]),
            commit=text(value.get("commit", "")),
            previous_commit=text(value.get("previous_commit", "")),
            reason=None if value.get("reason") is None else text(value["reason"]),
            backup_id=None if value.get("backup_id") is None else text(value["backup_id"]),
            images={text(k): text(v) for k, v in images.items()},
            requires_recovery=value.get("requires_recovery") is True,
        )


@dataclass(frozen=True)
class Config:
    app_dir: Path
    state_dir: Path
    runtime_dir: Path
    backend_project: str
    proxy: str = ""
    frontend_project: str = "agenticos-frontend"
    api_gid: int = 1000
    min_free_bytes: int = 4 * 1024**3
    drain_seconds: int = 900

    @classmethod
    def read(cls, path: Path) -> Self:
        value = json_object(path.read_bytes())
        return cls(
            app_dir=Path(text(value["app_dir"])).resolve(),
            state_dir=Path(text(value["state_dir"])).resolve(),
            runtime_dir=Path(text(value["runtime_dir"])).resolve(),
            backend_project=text(value["backend_project"]),
            proxy=text(value.get("proxy", "")),
            frontend_project=text(value.get("frontend_project", "agenticos-frontend")),
            api_gid=int(number(value.get("api_gid", 1000))),
            min_free_bytes=int(number(value.get("min_free_bytes", 4 * 1024**3))),
            drain_seconds=int(number(value.get("drain_seconds", 900))),
        )


class Commands:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        output: BinaryIO | None = None,
        timeout: int = 1200,
        user: int | None = None,
        group: int | None = None,
    ) -> str:
        if not args or args[0] not in {"docker", "git"}:
            raise Refused("unsupported_command")
        try:
            completed = subprocess.run(  # noqa: S603 - fixed executable; argv is built only by Compose/Updater
                args,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output or subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=True,
                user=user,
                group=group,
            )
        except subprocess.CalledProcessError as exc:
            stale_health = (
                args[:2] == ["docker", "compose"]
                and "up" in args
                and isinstance(exc.stderr, bytes)
                and b"is unhealthy" in exc.stderr
            )
            raise Refused("stale_health" if stale_health else "command_failed") from exc
        except (subprocess.SubprocessError, OSError) as exc:
            raise Refused("command_failed") from exc
        return completed.stdout.decode().strip() if output is None else ""


class Compose:
    def __init__(self, config: Config, commands: Commands):
        self.config, self.commands = config, commands

    def env(self, *, release: str | None = None) -> dict[str, str]:
        env = dict(os.environ)
        if release:
            env["AGENTICOS_VERSION"] = release
        env["UPDATE_STATE_DIR"] = str(self.config.runtime_dir)
        docker_gid = env.get("DOCKER_GID") or self.values().get("DOCKER_GID")
        if docker_gid is None and self.values().get("SANDBOXD_TOKEN"):
            docker_gid = str(Path("/var/run/docker.sock").stat().st_gid)
        if docker_gid is not None:
            if not docker_gid.isdecimal():
                raise Refused("unsupported_configuration")
            env["DOCKER_GID"] = docker_gid
        return env

    def values(self) -> dict[str, str]:
        # Values are read as data, never sourced as a shell program.
        result: dict[str, str] = {}
        for line in (self.config.app_dir / "backend/.env").read_text().splitlines():
            match = re.fullmatch(r"([A-Z_][A-Z0-9_]*)=(.*)", line.strip())
            if match:
                result[match[1]] = match[2].strip().strip("\"'")
        return result

    def args(
        self, *, frontend: bool = False, checkout: Path | None = None, override: Path | None = None
    ) -> list[str]:
        checkout = checkout or self.config.app_dir
        values = self.values()
        proxy = self.config.proxy
        if proxy not in {"nginx", "traefik"}:
            raise Refused("unsupported_configuration")
        files = ["docker-compose-prod.frontend.yml"] if frontend else ["docker-compose-prod.yml"]
        if proxy == "traefik":
            files.append(
                "docker-compose-prod.frontend.traefik.yml"
                if frontend
                else "docker-compose-prod.traefik.yml"
            )
        if not frontend:
            files.append("docker-compose-prod.updater.yml")
        args = [
            "docker",
            "compose",
            "--project-directory",
            str(checkout),
            "--env-file",
            str(self.config.app_dir / "backend/.env"),
            "-p",
            self.config.frontend_project if frontend else self.config.backend_project,
        ]
        for filename in files:
            args += ["-f", str(checkout / filename)]
        if override is not None:
            args += ["-f", str(override)]
        if not frontend:
            if values.get("SANDBOXD_TOKEN"):
                args += ["--profile", "sandbox"]
            if values.get("VISUAL_RENDER_CDP_URL", "").rstrip("/") == "http://visual-render:9222":
                args += ["--profile", "visuals"]
            if values.get("BROWSER_SIGN_IN_CDP_URL", "").rstrip("/") == "http://browser:9222":
                args += ["--profile", "browser"]
        return args

    def run(
        self,
        args: list[str],
        *,
        frontend: bool = False,
        checkout: Path | None = None,
        override: Path | None = None,
        release: str | None = None,
        output: BinaryIO | None = None,
    ) -> str:
        return self.commands.run(
            self.args(frontend=frontend, checkout=checkout, override=override) + args,
            cwd=self.config.app_dir,
            env=self.env(release=release),
            output=output,
        )

    def services(
        self, *, frontend: bool = False, checkout: Path | None = None, release: str | None = None
    ) -> dict[str, object]:
        parsed = json_object(
            self.run(
                ["config", "--format", "json"],
                frontend=frontend,
                checkout=checkout,
                release=release,
            ).encode()
        )
        services = parsed.get("services")
        if not isinstance(services, dict):
            raise Refused("unsupported_configuration")
        arguments = self.args(frontend=frontend, checkout=checkout)
        active = {
            arguments[i + 1] for i, argument in enumerate(arguments[:-1]) if argument == "--profile"
        }
        selected: dict[str, object] = {}
        for key, value in services.items():
            if not isinstance(value, dict):
                raise Refused("unsupported_configuration")
            profiles = value.get("profiles", [])
            if not isinstance(profiles, list) or not all(
                isinstance(item, str) for item in profiles
            ):
                raise Refused("unsupported_configuration")
            if not profiles or any(item in active for item in profiles):
                selected[text(key)] = value
        return selected

    def cid(self, service: str, *, frontend: bool = False) -> str:
        cid = self.run(["ps", "-a", "-q", service], frontend=frontend)
        if not re.fullmatch(r"[a-f0-9]{12,64}", cid):
            raise Refused("unsupported_configuration")
        return cid


class Updater:
    def __init__(self, config: Config, commands: Commands | None = None):
        self.config, self.commands = config, commands or Commands()
        self.compose = Compose(config, self.commands)
        self.lock = threading.RLock()
        self.operation: Operation | None = None
        self.stop = threading.Event()
        config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        config.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        config.state_dir.chmod(0o710)
        os.chown(config.state_dir, -1, config.app_dir.stat().st_gid)
        os.chown(config.runtime_dir, -1, config.api_gid)
        state = config.state_dir / "operation.json"
        if state.exists():
            self.operation = Operation.parse(json_object(state.read_bytes()))
            # /run may be recreated on a host reboot. The durable operation must
            # restore admission control before serving administrator requests.
            if self.operation.requires_recovery:
                self.drain(on=True)
            if self.operation.phase not in FINAL | {"ready", "scheduled"}:
                self.operation.reason = "interrupted"
                self.update("failed")
        self.drain(on=self.operation.requires_recovery if self.operation else False)

    def update(self, phase: Phase, *, reason: str | None = None) -> None:
        with self.lock:
            if self.operation is None:
                raise Refused("no_operation")
            self.operation.phase, self.operation.updated_at = phase, time.time()
            if reason:
                self.operation.reason = reason
            atomic_json(self.config.state_dir / "operation.json", asdict(self.operation))

    def status(self) -> dict[str, object]:
        with self.lock:
            return {"operation": asdict(self.operation) if self.operation else None}

    def prepare(self, release: str) -> None:
        release = version(release)
        with self.lock:
            control = self.config.runtime_dir / "control.json"
            if control.exists() and json_object(control.read_bytes()).get("draining") is True:
                raise Refused("manual_recovery_required")
            if self.operation and self.operation.phase not in FINAL:
                raise Refused("operation_active")
            self.operation = Operation(
                uuid.uuid4().hex, release, "preparing", time.time(), time.time()
            )
            self.update("preparing")

    def apply(self, identifier: str, scheduled_for: float | None) -> None:
        with self.lock:
            operation = self.operation
            if not operation or operation.id != identifier or operation.phase != "ready":
                raise Refused("not_ready")
            now = time.time()
            if scheduled_for is not None and not now <= scheduled_for <= now + 7 * 86400:
                raise Refused("invalid_schedule")
            operation.scheduled_for = scheduled_for or now
            self.update("scheduled")

    def cancel(self, identifier: str) -> None:
        with self.lock:
            if (
                not self.operation
                or self.operation.id != identifier
                or self.operation.phase not in {"ready", "scheduled"}
            ):
                raise Refused("cannot_cancel")
            self.update("cancelled")

    def git(self, *args: str) -> str:
        owner = self.config.app_dir.stat()
        env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        return self.commands.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                f"safe.directory={self.config.app_dir}",
                *args,
            ],
            cwd=self.config.app_dir,
            env=env,
            user=owner.st_uid,
            group=owner.st_gid,
        )

    def backup(self, operation: Operation, *, final: bool) -> None:
        folder = (
            self.config.state_dir / "backups" / operation.id / ("final" if final else "prepared")
        )
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        with (folder / "database.dump").open("wb") as output:
            self.compose.run(
                [
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-c",
                    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
                ],
                output=output,
            )
        if (folder / "database.dump").stat().st_size == 0:
            raise Refused("backup_failed")
        self.commands.run(
            ["docker", "cp", f"{self.compose.cid('app')}:/app/media", str(folder / "media")],
            cwd=self.config.app_dir,
        )
        shutil.copy2(self.config.app_dir / "backend/.env", folder / "backend.env")
        (folder / "backend.env").chmod(0o600)
        atomic_json(
            folder / "restore.json",
            {
                "previous_commit": operation.previous_commit,
                "target_commit": operation.commit,
                "images": operation.images,
                "consistent": final,
            },
        )
        operation.backup_id = f"{operation.id}/{'final' if final else 'prepared'}"

    def check_space(self, *, copies: int) -> None:
        size = int(
            self.compose.run(
                [
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-c",
                    'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "SELECT pg_database_size(current_database())"',
                ]
            )
        )
        media = self.compose.run(["exec", "-T", "app", "du", "-sk", "/app/media"])
        media_size = int(media.split()[0]) * 1024
        if (
            size < 0
            or media_size < 0
            or shutil.disk_usage(self.config.state_dir).free
            < copies * (size + media_size) + self.config.min_free_bytes
        ):
            raise Refused("insufficient_disk")

    def _prepare(self, operation: Operation) -> None:
        for command, minimum in (
            (["docker", "version", "--format", "{{.Server.Version}}"], (24, 0)),
            (["docker", "compose", "version", "--short"], (2, 24)),
        ):
            match = re.match(
                r"^v?(\d+)\.(\d+)", self.commands.run(command, cwd=self.config.app_dir)
            )
            if not match or (int(match[1]), int(match[2])) < minimum:
                raise Refused("unsupported_docker_version")
        worker = self.compose.cid("worker")
        hostname = self.commands.run(
            ["docker", "inspect", "--format", "{{.Config.Hostname}}", worker],
            cwd=self.config.app_dir,
        )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", hostname):
            raise Refused("unsupported_configuration")
        query = "SELECT COALESCE(json_agg(DISTINCT hostname), '[]'::json) FROM background_workers WHERE heartbeat_at > now() - interval '2 minutes';"
        remote: object = json.loads(
            self.compose.run(
                [
                    "exec",
                    "-T",
                    "db",
                    "sh",
                    "-c",
                    'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"',
                    "sh",
                    query,
                ]
            )
        )
        if not isinstance(remote, list) or any(item != hostname for item in remote):
            raise Refused("multi_host_requires_pipeline")
        values = self.compose.values()
        if values.get("MEDIA_DIR", "./media") not in {"./media", "media", "/app/media"}:
            raise Refused("custom_media_requires_pipeline")
        if values.get("FILE_STORAGE_BACKEND", "local") != "local":
            raise Refused("external_storage_requires_pipeline")
        if shutil.disk_usage(self.config.state_dir).free < self.config.min_free_bytes:
            raise Refused("insufficient_disk")
        if self.git("status", "--porcelain", "--untracked-files=no"):
            raise Refused("checkout_modified")
        operation.previous_commit = self.git("rev-parse", "HEAD")
        with_release = HTTPSConnection("api.github.com", timeout=10)
        try:
            with_release.request(
                "GET",
                RELEASES + "v" + operation.version,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "AgenticOS-Updater",
                },
            )
            response = with_release.getresponse()
            if response.status != 200:
                raise Refused("invalid_release")
            data = response.read(1024 * 1024 + 1)
        finally:
            with_release.close()
        if len(data) > 1024 * 1024:
            raise Refused("invalid_release")
        release = json_object(data)
        if (
            release.get("draft") is not False
            or release.get("prerelease") is not False
            or release.get("tag_name") != "v" + operation.version
        ):
            raise Refused("invalid_release")
        self.git(
            "fetch",
            "--no-tags",
            REPO,
            "refs/heads/main:refs/agenticos-updater/main",
            f"refs/tags/v{operation.version}:refs/tags/v{operation.version}",
        )
        operation.commit = self.git("rev-parse", f"refs/tags/v{operation.version}^{{commit}}")
        self.git("merge-base", "--is-ancestor", operation.commit, "refs/agenticos-updater/main")
        current = re.search(
            r'^version = "([^"]+)"',
            (self.config.app_dir / "backend/pyproject.toml").read_text(),
            re.MULTILINE,
        )
        if not current or tuple(map(int, operation.version.split("."))) <= tuple(
            map(int, version(current[1]).split("."))
        ):
            raise Refused("not_newer")
        operation_dir = self.config.state_dir / operation.id
        operation_dir.mkdir(mode=0o700)
        owner = self.config.app_dir.stat()
        os.chown(operation_dir, owner.st_uid, owner.st_gid)
        checkout = operation_dir / "checkout"
        self.git("worktree", "add", "--detach", str(checkout), operation.commit)
        shutil.copy2(self.config.app_dir / "backend/.env", checkout / "backend/.env")
        (checkout / "backend/.env").chmod(0o600)
        if not (checkout / "docker-compose-prod.updater.yml").exists():
            raise Refused("unsupported_release")
        tag = "sha-" + operation.commit[:7]
        for frontend in (False, True):
            before, after = (
                self.compose.services(frontend=frontend),
                self.compose.services(frontend=frontend, checkout=checkout, release=tag),
            )
            if set(before) - set(after):
                raise Refused("removed_services_require_pipeline")
            for name, service in after.items():
                if not isinstance(service, dict):
                    raise Refused("unsupported_configuration")
                image = text(service.get("image", ""))
                if not image.startswith("ghcr.io/vstorm-co/agenticos-"):
                    previous = before.get(name)
                    if not isinstance(previous, dict) or previous.get("image") != image:
                        raise Refused("infrastructure_change_requires_pipeline")
            self.compose.run(["pull", "--quiet"], frontend=frontend, checkout=checkout, release=tag)
            pinned: dict[str, object] = {}
            for name, service in after.items():
                if not isinstance(service, dict):
                    raise Refused("unsupported_configuration")
                image = text(service.get("image", ""))
                if image.startswith("ghcr.io/vstorm-co/agenticos-"):
                    digest = self.commands.run(
                        [
                            "docker",
                            "image",
                            "inspect",
                            "--format",
                            "{{index .RepoDigests 0}}",
                            image,
                        ],
                        cwd=self.config.app_dir,
                    )
                    if not re.fullmatch(
                        r"ghcr.io/vstorm-co/agenticos-[a-z]+@sha256:[a-f0-9]{64}", digest
                    ):
                        raise Refused("invalid_image")
                    operation.images[name] = digest
                    pinned[name] = {"image": digest}
            atomic_json(
                self.config.state_dir
                / f"{operation.id}-{'frontend' if frontend else 'backend'}.json",
                {"services": pinned},
            )
        self.check_space(copies=2)
        self.backup(operation, final=False)
        self.update("ready")

    def drain(self, *, on: bool) -> None:
        if self.operation is not None:
            self.operation.requires_recovery = on
            atomic_json(self.config.state_dir / "operation.json", asdict(self.operation))
        atomic_json(
            self.config.runtime_dir / "control.json", {"draining": on}, gid=self.config.api_gid
        )

    def active_work(self) -> int:
        # The query returns one integer, never a transcript, account or job payload.
        stale_seconds = float(self.compose.values().get("STALE_RUN_REAPED_AFTER_SECONDS", "120"))
        if not math.isfinite(stale_seconds) or stale_seconds <= 0:
            raise Refused("unsupported_configuration")
        # Match the stale-run and voice reapers; expired leases cannot finish
        # while new job claims are closed, and must not hold draining forever.
        query = (
            "SELECT (SELECT count(*) FROM agent_runs WHERE status = 'running' "  # noqa: S608 - only a finite, positive float is interpolated
            "AND modality != 'voice' AND COALESCE(GREATEST(heartbeat_at, updated_at, started_at), "
            f"created_at) >= now() - make_interval(secs => {stale_seconds})) + "
            "(SELECT count(*) FROM background_jobs WHERE status = 'running' "
            "AND lease_until >= now()) + (SELECT count(*) FROM voice_calls "
            "WHERE ended_at IS NULL AND heartbeat_at >= now() - interval '45 seconds');"
        )
        result = self.compose.run(
            [
                "exec",
                "-T",
                "db",
                "sh",
                "-c",
                'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"',
                "sh",
                query,
            ]
        )
        return int(result)

    def healthy(self, service: str, *, frontend: bool) -> bool:
        cid = self.compose.cid(service, frontend=frontend)
        status = self.commands.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", cid],
            cwd=self.config.app_dir,
        )
        return status == "healthy"

    def start_services(self, *, frontend: bool, override: Path, release: str) -> None:
        args = ["up", "-d", "--pull", "never", "--wait", "--wait-timeout", "180"]
        try:
            self.compose.run(args, frontend=frontend, override=override, release=release)
        except Refused as exc:
            if exc.code != "stale_health":
                raise
            if self.stop.wait(15):
                raise Refused("interrupted") from exc
            self.compose.run(args, frontend=frontend, override=override, release=release)

    def _apply(self, operation: Operation) -> None:
        if self.git("rev-parse", "HEAD") != operation.previous_commit or self.git(
            "status", "--porcelain", "--untracked-files=no"
        ):
            raise Refused("checkout_changed")
        self.update("draining")
        self.drain(on=True)
        deadline, quiet = time.monotonic() + self.config.drain_seconds, 0
        while time.monotonic() < deadline:
            quiet = quiet + 1 if self.active_work() == 0 else 0
            if quiet >= 3:
                break
            if self.stop.wait(5):
                raise Refused("interrupted")
        else:
            raise Refused("drain_timeout")
        self.check_space(copies=1)
        self.update("backing_up")
        self.compose.run(["stop", "--timeout", "40", "app", "worker"])
        self.backup(operation, final=True)
        self.update("applying")
        self.git("checkout", "--detach", operation.commit)
        path = self.config.app_dir / "backend/.env"
        owner = path.stat()
        env = path.read_text()
        env = re.sub(r"^AGENTICOS_VERSION=.*\n?", "", env, flags=re.MULTILINE)
        temporary = path.with_name(".env.update")
        temporary.write_text(env.rstrip() + "\nAGENTICOS_VERSION=" + operation.version + "\n")
        temporary.chmod(0o600)
        os.chown(temporary, owner.st_uid, owner.st_gid)
        temporary.replace(path)
        backend_override = self.config.state_dir / f"{operation.id}-backend.json"
        self.compose.run(
            ["run", "--rm", "--no-deps", "-T", "migrate"],
            override=backend_override,
            release=operation.version,
        )
        for frontend in (False, True):
            override = (
                self.config.state_dir
                / f"{operation.id}-{'frontend' if frontend else 'backend'}.json"
            )
            self.start_services(frontend=frontend, override=override, release=operation.version)
        self.update("checking")
        if not self.healthy("app", frontend=False) or not self.healthy("frontend", frontend=True):
            raise Refused("health_failed")
        self.compose.run(
            [
                "exec",
                "-T",
                "app",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=10)",
            ]
        )
        self.drain(on=False)
        self.update("succeeded")

    def tick(self) -> None:
        with self.lock:
            operation = self.operation
            if not operation or operation.phase not in {"preparing", "scheduled"}:
                return
            if operation.phase == "scheduled" and (operation.scheduled_for or 0) > time.time():
                return
            # Claim under the request lock so cancellation cannot race the worker.
            preparing = operation.phase == "preparing"
            self.update("preparing" if preparing else "draining")
        try:
            if preparing:
                self._prepare(operation)
            else:
                self._apply(operation)
        except (Refused, OSError, ValueError, HTTPException) as exc:
            reason = exc.code if isinstance(exc, Refused) else "operation_failed"
            if operation.phase == "backing_up":
                try:
                    self.compose.run(["start", "app", "worker"])
                except Refused:
                    self.update("failed", reason="manual_recovery_required")
                    return
            if operation.phase not in {"applying", "checking"}:
                self.drain(on=False)
            # After migration may have started, stay closed for manual recovery.
            self.update("failed", reason=reason)

    def run(self) -> None:
        while not self.stop.is_set():
            self.tick()
            self.stop.wait(1)


class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    updater: Updater


class Handler(BaseHTTPRequestHandler):
    timeout = 5

    @property
    def updater(self) -> Updater:
        if not isinstance(self.server, UnixHTTPServer):
            raise TypeError("Updater requires a Unix HTTP server")
        return self.server.updater

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - preserve the stdlib override signature
        return

    def address_string(self) -> str:
        return "local"

    def reply(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self.reply(200, self.updater.status()) if self.path == "/v1/status" else self.reply(
            404, {"error": "not_found"}
        )

    def request_data(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096:
            raise Refused("invalid_payload")
        return json_object(self.rfile.read(length))

    def dispatch(self, data: dict[str, object]) -> None:
        updater = self.updater
        actor = str(uuid.UUID(text(data.pop("actor_id", None))))
        if self.path not in {"/v1/prepare", "/v1/apply", "/v1/cancel"}:
            raise Refused("invalid_payload")
        if self.path == "/v1/prepare" and set(data) == {"version"}:
            version(data["version"])
        elif self.path in {"/v1/apply", "/v1/cancel"}:
            allowed = {"id", "scheduled_for"} if self.path == "/v1/apply" else {"id"}
            if not set(data) <= allowed or not ID.fullmatch(text(data.get("id"))):
                raise Refused("invalid_payload")
            if data.get("scheduled_for") is not None:
                number(data["scheduled_for"])
        else:
            raise Refused("invalid_payload")
        audit = updater.config.state_dir / "audit.jsonl"
        with audit.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"at": time.time(), "actor_id": actor, "action": self.path, "parameters": data}
                )
                + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        if self.path == "/v1/prepare" and set(data) == {"version"}:
            updater.prepare(version(data["version"]))
        elif self.path == "/v1/apply" and set(data) <= {"id", "scheduled_for"}:
            identifier = text(data.get("id"))
            updater.apply(
                identifier,
                None if data.get("scheduled_for") is None else number(data["scheduled_for"]),
            )
        elif self.path == "/v1/cancel" and set(data) == {"id"}:
            updater.cancel(text(data["id"]))
        else:
            raise Refused("invalid_payload")

    def do_POST(self) -> None:
        try:
            self.dispatch(self.request_data())
            self.reply(202, self.updater.status())
        except (Refused, ValueError) as exc:
            self.reply(409, {"error": exc.code if isinstance(exc, Refused) else "invalid_payload"})


def serve(config: Config) -> None:
    config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # flock is held for this process's lifetime, including an API restart.
    with (config.state_dir / "agent.lock").open("w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        updater = Updater(config)
        socket = config.runtime_dir / "agent.sock"
        socket.unlink(missing_ok=True)
        with UnixHTTPServer(str(socket), Handler) as server:
            server.updater = updater
            socket.chmod(0o660)
            os.chown(socket, -1, config.api_gid)
            thread = threading.Thread(target=updater.run, name="compose-updater")
            thread.start()

            def stop(_signum: int, _frame: object) -> None:
                updater.stop.set()
                threading.Thread(target=server.shutdown, daemon=True).start()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            try:
                server.serve_forever()
            finally:
                updater.stop.set()
                thread.join()
                socket.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    serve(Config.read(parser.parse_args().config))
