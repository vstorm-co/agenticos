#!/usr/bin/env python3
"""Conservative, host-local Docker image retention; dry-run unless --apply is given.

This helper manages images only. Other image writers must share its deployment
flock or remain quiesced throughout the maintenance window; the operator must
explicitly acknowledge that condition. Docker provides no atomic
inspect-and-remove API, so reinspection cannot replace coordinated writers.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
REPOSITORY_PART = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*\Z")
TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
MAX_POLICY_BYTES = 64 * 1024
MAX_DOCKER_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_INVENTORY_ITEMS = 10000
DOCKER_TIMEOUT_SECONDS = 60
GIB = 1024**3


class RetentionError(Exception):
    """A failed safety check; an apply stops at the first such failure."""

    def __init__(
        self,
        message: str,
        *,
        removed_image_ids: tuple[str, ...] = (),
        attempted_image_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.removed_image_ids = removed_image_ids
        self.attempted_image_id = attempted_image_id


@dataclass(frozen=True)
class Component:
    service: str
    repository: str
    current_image_id: str
    previous_successful_image_id: str


@dataclass(frozen=True)
class Policy:
    docker_host: str
    daemon_id: str
    compose_project: str
    lock_file: Path
    repositories: frozenset[str]
    components: tuple[Component, ...]
    minimum_age_days: int = 7
    max_removals: int = 10
    min_free_gib: int = 20
    min_free_percent: int = 20


@dataclass(frozen=True)
class Image:
    image_id: str
    created: datetime
    repo_tags: tuple[str, ...]
    repo_digests: tuple[str, ...]
    size_bytes: int = 0


@dataclass(frozen=True)
class Container:
    container_id: str
    image_id: str
    configured_image: str
    project: str | None
    service: str | None
    running: bool
    status: str
    health: str | None


@dataclass(frozen=True)
class DaemonInfo:
    daemon_id: str
    docker_root_dir: Path


@dataclass(frozen=True)
class Snapshot:
    info: DaemonInfo
    images: dict[str, Image]
    containers: tuple[Container, ...]


@dataclass(frozen=True)
class Plan:
    protected_ids: frozenset[str]
    candidates: tuple[Image, ...]
    skipped: tuple[tuple[str, str], ...]
    eligible_count: int


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise RetentionError(f"{name} must be a JSON object")
    return dict(value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise RetentionError(f"{name} must be a nonempty string")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RetentionError(f"{name} contains whitespace or control characters")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RetentionError(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def _fields(record: dict[str, object], required: set[str], optional: set[str], name: str) -> None:
    if not required <= record.keys() or record.keys() - required - optional:
        raise RetentionError(f"{name} has missing or unknown fields")


def _absolute_path(value: object, name: str) -> Path:
    text = _text(value, name)
    path = Path(text)
    if not path.is_absolute() or ".." in path.parts or str(path) != text or text == "/":
        raise RetentionError(f"{name} must be a normalized absolute local path")
    return path


def _socket_path(host: object) -> Path:
    text = _text(host, "docker_host")
    if not text.startswith("unix:///") or any(char in text for char in "?#"):
        raise RetentionError("docker_host must explicitly name a local unix:/// socket")
    return _absolute_path(text[len("unix://"):], "Docker socket")


def _repository(value: object) -> str:
    text = _text(value, "repository")
    parts = text.split("/")
    if ":" in parts[0]:
        host, separator, port = parts[0].partition(":")
        if len(parts) < 2 or not separator or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise RetentionError("Repository allowlist entries must be exact repository names, without tags")
        parts[0] = host
    if any(REPOSITORY_PART.fullmatch(part) is None for part in parts):
        raise RetentionError("Repository allowlist entries must be exact repository names, without tags or patterns")
    return text


def _image_id(value: object, name: str) -> str:
    text = _text(value, name)
    if IMAGE_ID.fullmatch(text) is None:
        raise RetentionError(f"{name} must be a full sha256 Docker image config ID")
    return text


def parse_policy(data: object) -> Policy:
    """Validate a policy with no wildcard, remote-host or unknown-field defaults."""
    record = _object(data, "policy")
    _fields(
        record,
        {"schema_version", "docker_host", "daemon_id", "compose_project", "lock_file", "repositories", "components"},
        {"minimum_age_days", "max_removals", "min_free_gib", "min_free_percent"},
        "policy",
    )
    _integer(record["schema_version"], "schema_version", 1, 1)
    host = _text(record["docker_host"], "docker_host")
    _socket_path(host)
    daemon_id = _text(record["daemon_id"], "daemon_id")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{3,255}", daemon_id) is None:
        raise RetentionError("daemon_id must be the exact ID returned by docker info")
    project = _text(record["compose_project"], "compose_project")
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", project) is None:
        raise RetentionError("compose_project must be an exact Compose project name")
    lock_file = _absolute_path(record["lock_file"], "lock_file")
    repository_values = record["repositories"]
    if not isinstance(repository_values, list) or not 1 <= len(repository_values) <= 100:
        raise RetentionError("repositories must be a nonempty explicit allowlist")
    repositories = frozenset(_repository(value) for value in repository_values)
    if len(repositories) != len(repository_values):
        raise RetentionError("repositories contains duplicate entries")
    component_values = _object(record["components"], "components")
    if not 1 <= len(component_values) <= 100:
        raise RetentionError("components must name the deployed Compose services")
    components: list[Component] = []
    for service, value in sorted(component_values.items()):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", service) is None:
            raise RetentionError("Each component key must be an exact Compose service name")
        component = _object(value, "component")
        _fields(component, {"repository", "current_image_id", "previous_successful_image_id"}, set(), "component")
        repository = _repository(component["repository"])
        if repository not in repositories:
            raise RetentionError("A component repository is not in the repository allowlist")
        components.append(
            Component(
                service=service,
                repository=repository,
                current_image_id=_image_id(component["current_image_id"], "current_image_id"),
                previous_successful_image_id=_image_id(
                    component["previous_successful_image_id"], "previous_successful_image_id"
                ),
            )
        )
    if {component.repository for component in components} != repositories:
        raise RetentionError("Every allowlisted repository must have a configured component")
    return Policy(
        docker_host=host,
        daemon_id=daemon_id,
        compose_project=project,
        lock_file=lock_file,
        repositories=repositories,
        components=tuple(components),
        minimum_age_days=_integer(record.get("minimum_age_days", 7), "minimum_age_days", 1, 3650),
        max_removals=_integer(record.get("max_removals", 10), "max_removals", 1, 100),
        min_free_gib=_integer(record.get("min_free_gib", 20), "min_free_gib", 1, 1048576),
        min_free_percent=_integer(record.get("min_free_percent", 20), "min_free_percent", 1, 99),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise RetentionError("JSON contains a duplicate field")
        record[key] = value
    return record


def _invalid_constant(value: str) -> NoReturn:
    raise RetentionError("JSON contains a non-finite numeric value")


def _json(text: str, name: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise RetentionError(f"{name} returned invalid JSON") from exc


def _private_regular(file_stat: os.stat_result, name: str) -> None:
    if (
        not stat.S_ISREG(file_stat.st_mode)
        or file_stat.st_nlink != 1
        or file_stat.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(file_stat.st_mode) not in {0o400, 0o600}
    ):
        raise RetentionError(f"{name} must be a private regular file owned by this user or root (mode 0600/0400)")


def load_policy(path: Path) -> Policy:
    """Read a small private policy without following its final symlink."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            _private_regular(os.fstat(stream.fileno()), "Policy")
            content = stream.read(MAX_POLICY_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise RetentionError("Cannot safely read the private policy file") from exc
    if len(content.encode("utf-8")) > MAX_POLICY_BYTES:
        raise RetentionError("Policy file exceeds the size limit")
    return parse_policy(_json(content, "Policy"))


@contextmanager
def deployment_lock(path: Path) -> Iterator[int]:
    """Take the same exclusive, nonblocking flock used by all deployment writers."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise RetentionError("Cannot open the deployment lock; provision its directory first") from exc
    try:
        _private_regular(os.fstat(fd), "Deployment lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RetentionError("Deployment lock is held or unavailable; no cleanup was started") from exc
        verify_lock(fd, path)
        yield fd
    finally:
        os.close(fd)


def verify_lock(fd: int, path: Path) -> None:
    """Refuse a replaced lock file, which would permit another writer to enter."""
    try:
        opened, current = os.fstat(fd), path.lstat()
    except OSError as exc:
        raise RetentionError("Deployment lock disappeared") from exc
    _private_regular(current, "Deployment lock")
    if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
        raise RetentionError("Deployment lock changed during cleanup")


def alias_repository(alias: str, *, digest: bool) -> str | None:
    """Return an exact repository, or unknown; never infer ownership from one alias."""
    try:
        if digest:
            repository, separator, value = alias.partition("@")
            if not separator or IMAGE_ID.fullmatch(value) is None:
                return None
        else:
            repository, separator, value = alias.rpartition(":")
            if not separator or TAG.fullmatch(value) is None or "@" in repository:
                return None
        return _repository(repository)
    except RetentionError:
        return None


def image_repositories(image: Image) -> frozenset[str] | None:
    aliases = [alias_repository(alias, digest=False) for alias in image.repo_tags]
    aliases.extend(alias_repository(alias, digest=True) for alias in image.repo_digests)
    if not aliases or None in aliases:
        return None
    return frozenset(value for value in aliases if value is not None)


def _known_repositories(image: Image) -> set[str]:
    """Known aliases still identify managed activity when another alias is unknown."""
    return {
        repository
        for digest, aliases in ((False, image.repo_tags), (True, image.repo_digests))
        for alias in aliases
        if (repository := alias_repository(alias, digest=digest)) is not None
    }


def _configured_repository(reference: str) -> str | None:
    if IMAGE_ID.fullmatch(reference) is not None:
        return None
    if "@" in reference:
        return alias_repository(reference, digest=True)
    if ":" in reference.rsplit("/", 1)[-1]:
        return alias_repository(reference, digest=False)
    try:
        return _repository(reference)
    except RetentionError:
        return None


def plan_images(policy: Policy, snapshot: Snapshot, now: datetime) -> Plan:
    """Validate deployed pins, then plan only owned, old and unreferenced image IDs."""
    if snapshot.info.daemon_id != policy.daemon_id:
        raise RetentionError("Docker daemon ID does not match the private policy")
    if now.tzinfo is None:
        raise RetentionError("Retention time must include a timezone")
    components = {component.service: component for component in policy.components}
    protected: set[str] = set()
    for component in policy.components:
        for image_id in (component.current_image_id, component.previous_successful_image_id):
            image = snapshot.images.get(image_id)
            if image is None or component.repository not in _known_repositories(image):
                raise RetentionError(f"Missing or stale image pin for component {component.service}")
            protected.add(image_id)
    healthy_services: set[str] = set()
    for container in snapshot.containers:
        protected.add(container.image_id)
        image = snapshot.images.get(container.image_id)
        if image is None:
            raise RetentionError("A container references an image missing from the complete inventory")
        active = container.running or container.status in {"running", "paused", "restarting"}
        if not active:
            continue
        managed = bool(_known_repositories(image) & policy.repositories)
        managed = managed or _configured_repository(container.configured_image) in policy.repositories
        configured = container.project == policy.compose_project and container.service in components
        if not managed and not configured:
            continue
        if container.project != policy.compose_project:
            raise RetentionError("An active managed image belongs to a different Compose project")
        component = components.get(container.service or "")
        if component is None or container.image_id != component.current_image_id:
            raise RetentionError("An unexpected active image or service uses a managed repository")
        if not container.running or container.status != "running" or container.health != "healthy":
            raise RetentionError(f"Current component {component.service} is not running and healthy")
        healthy_services.add(component.service)
    if healthy_services != components.keys():
        raise RetentionError("Current pins are not running healthy containers in the configured Compose project")

    eligible: list[Image] = []
    skipped: list[tuple[str, str]] = []
    cutoff = now - timedelta(days=policy.minimum_age_days)
    for image in sorted(snapshot.images.values(), key=lambda item: (item.created, item.image_id)):
        repositories = image_repositories(image)
        if image.image_id in protected:
            reason = "container reference or current/previous-successful pin"
        elif repositories is None:
            reason = "unknown ownership (including dangling or unrecognized aliases)"
        elif not repositories <= policy.repositories:
            reason = "unowned or mixed repository aliases"
        elif len(image.repo_tags) > 1:
            reason = "multiple tags; aliases are not removed separately"
        elif len(repositories) > 1:
            reason = "multiple repository aliases; leave the complete image intact"
        elif image.created > cutoff:
            reason = "younger than the configured age floor"
        else:
            eligible.append(image)
            continue
        skipped.append((image.image_id, reason))
    for image in eligible[policy.max_removals:]:
        skipped.append((image.image_id, "per-run removal limit"))
    return Plan(frozenset(protected), tuple(eligible[:policy.max_removals]), tuple(skipped), len(eligible))


def _string_array(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RetentionError(f"Docker {name} is not an array of strings")
    return tuple(sorted(set(value)))


def _parse_image(value: object) -> Image:
    row = _object(value, "Docker image")
    image_id = _image_id(row.get("Id"), "Docker image Id")
    created_text = _text(row.get("Created"), "Docker image Created")
    try:
        created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetentionError("Docker image Created is not a valid timestamp") from exc
    if created.tzinfo is None:
        raise RetentionError("Docker image Created has no timezone")
    if "RepoTags" not in row or "RepoDigests" not in row:
        raise RetentionError("Docker image aliases are missing from inspect output")
    return Image(
        image_id,
        created.astimezone(UTC),
        _string_array(row["RepoTags"], "RepoTags"),
        _string_array(row["RepoDigests"], "RepoDigests"),
        _integer(row.get("Size"), "Docker image Size", 0, 2**63 - 1),
    )


def _parse_container(value: object) -> Container:
    row = _object(value, "Docker container")
    container_id = _text(row.get("Id"), "Docker container Id")
    if CONTAINER_ID.fullmatch(container_id) is None:
        raise RetentionError("Docker container Id is not a full immutable ID")
    config = _object(row.get("Config"), "Docker container Config")
    labels = {} if config.get("Labels") is None else _object(config["Labels"], "Docker container labels")
    if any(not isinstance(value, str) for value in labels.values()):
        raise RetentionError("Docker container labels contain non-string values")
    state = _object(row.get("State"), "Docker container State")
    running = state.get("Running")
    if type(running) is not bool:
        raise RetentionError("Docker container Running is not a boolean")
    status = _text(state.get("Status"), "Docker container Status")
    if status not in {"created", "running", "paused", "restarting", "removing", "exited", "dead"}:
        raise RetentionError("Docker container has an unrecognized status")
    health = None
    if state.get("Health") is not None:
        health = _text(_object(state["Health"], "Docker health").get("Status"), "Docker health Status")
    project, service = labels.get(PROJECT_LABEL), labels.get(SERVICE_LABEL)
    return Container(
        container_id=container_id,
        image_id=_image_id(row.get("Image"), "Docker container Image"),
        configured_image=_text(config.get("Image"), "Docker container Config.Image"),
        project=project if isinstance(project, str) else None,
        service=service if isinstance(service, str) else None,
        running=running,
        status=status,
        health=health,
    )


class DockerClient:
    """Invoke only Docker inventory and single-image removal against an explicit local socket."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        socket_path = _socket_path(policy.docker_host)
        try:
            if not stat.S_ISSOCK(socket_path.stat().st_mode):
                raise RetentionError("Configured Docker endpoint is not a local Unix socket")
        except OSError as exc:
            raise RetentionError("Configured local Docker socket is unavailable") from exc

    def _run(self, *args: str) -> str:
        # An inherited context, TLS switch or API override must not redirect or
        # narrow the explicitly selected daemon's inventory.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("DOCKER_")}
        try:
            result = subprocess.run(
                ["docker", "--host", self.policy.docker_host, *args],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=DOCKER_TIMEOUT_SECONDS,
                env=environment,
            )
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise RetentionError("Docker command failed, timed out or returned undecodable output") from exc
        if result.returncode != 0:
            raise RetentionError(f"Docker {' '.join(args[:2])} failed (exit {result.returncode}); cleanup stopped")
        if len(result.stdout.encode("utf-8")) > MAX_DOCKER_OUTPUT_BYTES:
            raise RetentionError("Docker inventory exceeded the output size limit")
        return result.stdout

    def info(self) -> DaemonInfo:
        row = _object(_json(self._run("info", "--format", "{{json .}}"), "Docker info"), "Docker info")
        if row.get("ID") != self.policy.daemon_id or row.get("OSType") != "linux":
            raise RetentionError("Docker daemon ID or Linux host type does not match the private policy")
        return DaemonInfo(self.policy.daemon_id, _absolute_path(row.get("DockerRootDir"), "DockerRootDir"))

    def _ids(self, kind: str) -> tuple[str, ...]:
        lines = self._run(kind, "ls", "--all", "--quiet", "--no-trunc").splitlines()
        pattern = IMAGE_ID if kind == "image" else CONTAINER_ID
        if len(lines) > MAX_INVENTORY_ITEMS or any(pattern.fullmatch(line) is None for line in lines):
            raise RetentionError("Docker returned an incomplete or invalid immutable-ID inventory")
        return tuple(sorted(set(lines)))

    def _inspect(self, kind: str, ids: tuple[str, ...]) -> list[object]:
        rows: list[object] = []
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            values = _json(self._run(kind, "inspect", *batch), f"Docker {kind} inspect")
            if not isinstance(values, list) or len(values) != len(batch):
                raise RetentionError("Docker inspect returned a partial inventory")
            rows.extend(values)
        return rows

    def snapshot(self) -> Snapshot:
        info = self.info()
        image_ids = self._ids("image")
        images = [_parse_image(row) for row in self._inspect("image", image_ids)]
        container_ids = self._ids("container")
        containers = [_parse_container(row) for row in self._inspect("container", container_ids)]
        found_images = {image.image_id for image in images}
        if len(found_images) != len(images) or found_images != set(image_ids):
            raise RetentionError("Docker image inspect does not match its ID inventory")
        found_containers = {row.container_id for row in containers}
        if len(found_containers) != len(containers) or found_containers != set(container_ids):
            raise RetentionError("Docker container inspect does not match its ID inventory")
        # Re-list to catch a container or image appearing during inspection, even
        # when it would otherwise have fallen between the two inventories.
        if self._ids("image") != image_ids or self._ids("container") != container_ids or self.info() != info:
            raise RetentionError("Docker inventory changed while it was being inspected")
        return Snapshot(
            info,
            {image.image_id: image for image in images},
            tuple(sorted(containers, key=lambda row: row.container_id)),
        )

    def remove_image(self, image_id: str) -> None:
        self._run("image", "rm", "--no-prune", _image_id(image_id, "Removal image ID"))


def _same_snapshot(actual: Snapshot, initial: Snapshot, removed: tuple[str, ...]) -> None:
    expected = {key: value for key, value in initial.images.items() if key not in removed}
    if actual.info != initial.info or actual.containers != initial.containers or actual.images != expected:
        raise RetentionError("Docker image/container metadata or protected references drifted; cleanup stopped")


def apply_plan(
    policy: Policy,
    initial: Snapshot,
    plan: Plan,
    docker: DockerClient,
    now: datetime,
    *,
    before_delete: Callable[[], None] | None = None,
) -> tuple[str, ...]:
    """Remove a capped plan, rechecking all metadata immediately before every ID removal.

    The caller must hold deployment_lock for the entire operation. A successful
    Docker command is confirmed by a fresh inventory before reporting a deletion.
    """
    if plan != plan_images(policy, initial, now):
        raise RetentionError("The supplied deletion plan does not match the validated inventory")
    removed: list[str] = []
    attempted: str | None = None
    try:
        for candidate in plan.candidates:
            if before_delete is not None:
                before_delete()
            fresh = docker.snapshot()
            _same_snapshot(fresh, initial, tuple(removed))
            verified = plan_images(policy, fresh, now)
            if candidate not in verified.candidates or verified.protected_ids != plan.protected_ids:
                raise RetentionError("Candidate or protected image set changed; cleanup stopped")
            attempted = candidate.image_id
            docker.remove_image(candidate.image_id)
            after = docker.snapshot()
            if candidate.image_id in after.images:
                raise RetentionError("Docker did not remove the selected image ID; cleanup stopped")
            removed.append(candidate.image_id)
            attempted = None
            _same_snapshot(after, initial, tuple(removed))
        return tuple(removed)
    except RetentionError as exc:
        raise RetentionError(str(exc), removed_image_ids=tuple(removed), attempted_image_id=attempted) from exc


def disk_space(policy: Policy, info: DaemonInfo) -> dict[str, object]:
    """Read available space on DockerRootDir's local host filesystem; both floors apply."""
    try:
        if not info.docker_root_dir.is_dir():
            raise RetentionError("DockerRootDir is not a directory on this host; run the helper on the Docker host")
        usage = shutil.disk_usage(info.docker_root_dir)
    except OSError as exc:
        raise RetentionError("Cannot measure DockerRootDir free space on this host") from exc
    if usage.total <= 0 or not 0 <= usage.free <= usage.total:
        raise RetentionError("DockerRootDir returned invalid disk-space measurements")
    minimum_bytes = policy.min_free_gib * GIB
    sufficient = usage.free >= minimum_bytes and usage.free * 100 >= usage.total * policy.min_free_percent
    return {
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "free_percent": round(usage.free * 100 / usage.total, 2),
        "minimum_free_bytes": minimum_bytes,
        "minimum_free_percent": policy.min_free_percent,
        "sufficient": sufficient,
    }


def _image_report(image: Image) -> dict[str, object]:
    return {
        "image_id": image.image_id,
        "created": image.created.isoformat(),
        "repo_tags": list(image.repo_tags),
        "repo_digests": list(image.repo_digests),
        "size_bytes": image.size_bytes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True, help="Private host policy JSON (mode 0600/0400)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true", help="Apply a verified plan under the shared deployment flock")
    modes.add_argument(
        "--check-space", action="store_true", help="Pre-deploy disk guard only; no image removals or lock acquisition"
    )
    parser.add_argument(
        "--writers-coordinated",
        action="store_true",
        help=(
            "Required with --apply only: assert that all image writers and other cleanup share this lock "
            "or are quiesced for the entire maintenance window. This helper cannot verify that assertion."
        ),
    )
    args = parser.parse_args(argv)
    if args.apply != args.writers_coordinated:
        parser.error("--apply requires --writers-coordinated; the acknowledgment is only valid with --apply")
    confirmed_removals: tuple[str, ...] = ()
    try:
        policy = load_policy(args.policy)
        docker = DockerClient(policy)
        if args.check_space:
            info = docker.info()
            space = disk_space(policy, info)
            print(json.dumps(
                {"mode": "check-space", "docker_root_dir": str(info.docker_root_dir), "disk": space}, indent=2
            ))
            return 0 if space["sufficient"] else 3
        planning_time = datetime.now(UTC)

        def inventory_report() -> tuple[Snapshot, Plan, dict[str, object]]:
            snapshot = docker.snapshot()
            plan = plan_images(policy, snapshot, planning_time)
            report: dict[str, object] = {
                "mode": "apply" if args.apply else "dry-run",
                "daemon_id": snapshot.info.daemon_id,
                "compose_project": policy.compose_project,
                "docker_root_dir": str(snapshot.info.docker_root_dir),
                "disk": disk_space(policy, snapshot.info),
                "protected_image_count": len(plan.protected_ids),
                "eligible_image_count": plan.eligible_count,
                "planned_removals": [_image_report(image) for image in plan.candidates],
                "skipped": [{"image_id": image_id, "reason": reason} for image_id, reason in plan.skipped],
                "removed_image_ids": [],
            }
            return snapshot, plan, report

        if args.apply:
            with deployment_lock(policy.lock_file) as lock_fd:
                def revalidate() -> None:
                    verify_lock(lock_fd, policy.lock_file)
                    if load_policy(args.policy) != policy:
                        raise RetentionError("Private policy changed during cleanup")

                revalidate()
                snapshot, plan, report = inventory_report()
                confirmed_removals = apply_plan(
                    policy, snapshot, plan, docker, planning_time, before_delete=revalidate,
                )
                report["removed_image_ids"] = list(confirmed_removals)
                report["disk_after"] = disk_space(policy, snapshot.info)
        else:
            _, _, report = inventory_report()
        print(json.dumps(report, indent=2))
        return 0
    except RetentionError as exc:
        print(json.dumps({
            "status": "refused",
            "error": str(exc),
            "removed_image_ids": list(exc.removed_image_ids or confirmed_removals),
            "attempted_image_id": exc.attempted_image_id,
        }, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
