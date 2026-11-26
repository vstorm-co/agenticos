"""Live mounts reach their gateway without exposing the sandbox supervisor."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("gateway", "image", "enabled", "refused"),
    [
        ("", "", False, False),
        ("https://api.example.com/api/v1/project-filesystem", "export:1", True, False),
        ("https://api.example.com", "", False, True),
        ("", "export:1", False, True),
    ],
)
def test_deploy_enables_gateway_bridge_only_for_complete_opt_in(
    gateway: str, image: str, enabled: bool, refused: bool
) -> None:
    source = (ROOT / "scripts/deploy.sh").read_text()
    start = source.index('FILESYSTEM_GATEWAY="$(env_value')
    end = source.index("\n# The sandbox service is behind", start)
    script = (
        'env_value() { printenv "$1" || true; }\n'
        "BACKEND=(-f docker-compose-prod.yml -f docker-compose-prod.traefik.yml)\n"
        + source[start:end]
        + '\nprintf "%s\\n" "${BACKEND[@]}"\n'
    )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={
            **os.environ,
            "SANDBOXD_FILESYSTEM_GATEWAY_URL": gateway,
            "SANDBOXD_FILESYSTEM_EXPORT_IMAGE": image,
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if refused:
        assert result.returncode == 1
        assert "Configure both" in result.stderr
    else:
        assert result.returncode == 0
        expected = ["-f", "docker-compose-prod.yml", "-f", "docker-compose-prod.traefik.yml"]
        if enabled:
            expected.extend(["-f", "docker-compose.project-filesystem.yml"])
        assert result.stdout.splitlines() == expected


def test_gateway_overlay_keeps_supervisor_out_of_proxy_and_agents_out_of_control() -> None:
    overlay = yaml.safe_load((ROOT / "docker-compose.project-filesystem.yml").read_text())
    assert set(overlay["services"]) == {"sandboxd"}
    sandbox = overlay["services"]["sandboxd"]
    assert sandbox == {"networks": ["projectfs_gateway"]}
    assert overlay["networks"]["projectfs_gateway"] == {"driver": "bridge", "internal": False}
    base = yaml.safe_load((ROOT / "docker-compose-prod.yml").read_text())
    assert base["services"]["sandboxd"]["networks"] == ["data"]
    assert not base["services"]["sandboxd"].get("ports")
    assert base["services"]["sandboxd"]["environment"]["SANDBOXD_NETWORK_MODE"] == "none"
