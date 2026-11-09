"""Check the real Compose merge without contacting a container engine."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("socket", ["/run/podman/podman.sock", "/run/user/1000/podman/podman.sock"])
def test_podman_override_replaces_socket_and_shares_only_the_workspace_label(
    tmp_path: Path, socket: str
) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is needed for the offline merge check")
    version = subprocess.run(
        [docker, "compose", "version"], capture_output=True, timeout=10, check=False
    )
    if version.returncode:
        pytest.skip("Docker Compose CLI is needed for the offline merge check")
    workspace = str(tmp_path / "workspaces")
    result = subprocess.run(
        [
            docker,
            "compose",
            "--project-directory",
            str(tmp_path),
            "--env-file",
            os.devnull,
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(ROOT / "docker-compose-podman.yml"),
            "--profile",
            "sandbox",
            "config",
            "--format",
            "json",
        ],
        env={
            **os.environ,
            "SANDBOX_DOCKER_SOCKET": socket,
            "SANDBOX_WORKSPACE_ROOT": workspace,
            "DOCKER_GID": "0",
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    config = TypeAdapter(JsonValue).validate_json(result.stdout)
    assert isinstance(config, dict)
    services = config["services"]
    assert isinstance(services, dict)
    sandbox = services["sandboxd"]
    assert isinstance(sandbox, dict)
    volumes = sandbox["volumes"]
    assert isinstance(volumes, list)
    assert len(volumes) == 2
    mounted: dict[str, dict[str, JsonValue]] = {}
    for volume in volumes:
        assert isinstance(volume, dict)
        target = volume["target"]
        assert isinstance(target, str)
        mounted[target] = volume
    assert mounted["/var/run/docker.sock"]["source"] == socket
    socket_options = mounted["/var/run/docker.sock"]["bind"]
    assert isinstance(socket_options, dict)
    assert socket_options.get("create_host_path", False) is False
    assert "selinux" not in socket_options
    assert mounted[workspace]["source"] == workspace
    workspace_options = mounted[workspace]["bind"]
    assert isinstance(workspace_options, dict)
    assert workspace_options.get("create_host_path", False) is False
    assert workspace_options["selinux"] == "z"
    assert sandbox["security_opt"] == ["label=disable"]
    assert sandbox["group_add"] == ["0"]
    environment = sandbox["environment"]
    assert isinstance(environment, dict)
    assert environment["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert environment["SANDBOXD_SANDBOX_UID"] == "10001"
    app = services["app"]
    assert isinstance(app, dict)
    assert "security_opt" not in app
