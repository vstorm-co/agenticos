"""Live mounts reach their gateway without exposing the sandbox supervisor."""

import json
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
    gateway: str, image: str, enabled: bool, refused: bool, tmp_path: Path
) -> None:
    source = (ROOT / "scripts/deploy.sh").read_text()
    start = source.index('FILESYSTEM_GATEWAY="$(env_value')
    end = source.index("\n# The sandbox service is behind", start)
    script = (
        'env_value() { printenv "$1" || true; }\n'
        "BACKEND=(-f docker-compose-prod.yml -f docker-compose-prod.traefik.yml)\n"
        + source[start:end]
        + '\nprintf "%s\\n" "${BACKEND[@]}"\n'
        + 'if [ -n "${FILESYSTEM_OVERLAY:-}" ]; then printf "%s\\n" __OVERLAY__; cat "$FILESYSTEM_OVERLAY"; fi\n'
    )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={
            **os.environ,
            "SANDBOXD_FILESYSTEM_GATEWAY_URL": gateway,
            "SANDBOXD_FILESYSTEM_EXPORT_IMAGE": image,
            "TMPDIR": str(tmp_path),
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
        arguments, _, generated = result.stdout.partition("__OVERLAY__\n")
        actual = arguments.splitlines()
        if enabled:
            overlay_path = Path(actual[-1])
            assert overlay_path.is_absolute()
            assert not overlay_path.exists()
            expected.extend(["-f", str(overlay_path)])
            assert yaml.safe_load(generated) == yaml.safe_load(
                (ROOT / "docker-compose.project-filesystem.yml").read_text()
            )
        assert actual == expected
    assert not list(tmp_path.glob("agenticos-projectfs.*"))


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


@pytest.mark.skipif(shutil.which("docker") is None, reason="Compose CLI is required")
@pytest.mark.parametrize("proxy", [False, True])
def test_deployer_gateway_overlay_survives_a_target_that_predates_the_file(
    tmp_path: Path, proxy: bool
) -> None:
    for name in ("docker-compose-prod.yml", "docker-compose-prod.traefik.yml"):
        shutil.copy2(ROOT / name, tmp_path / name)
    assert not (tmp_path / "docker-compose.project-filesystem.yml").exists()
    source = (ROOT / "scripts/deploy.sh").read_text()
    start = source.index('FILESYSTEM_GATEWAY="$(env_value')
    end = source.index("\n# The sandbox service is behind", start)
    base = "BACKEND=(-f docker-compose-prod.yml"
    if proxy:
        base += " -f docker-compose-prod.traefik.yml"
    script = (
        'env_value() { printenv "$1" || true; }\n'
        + base
        + ")\n"
        + source[start:end]
        + '\ndocker compose --env-file /dev/null --profile sandbox "${BACKEND[@]}" config --no-env-resolution --format json\n'
    )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "SANDBOXD_FILESYSTEM_GATEWAY_URL": "https://api.example.com/api/v1/project-filesystem",
            "SANDBOXD_FILESYSTEM_EXPORT_IMAGE": "export:1",
            "POSTGRES_PASSWORD": "fixture",
            "REDIS_PASSWORD": "fixture",
            "API_DOMAIN": "api.example.com",
            "TMPDIR": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    resolved = json.loads(result.stdout)
    sandbox = resolved["services"]["sandboxd"]
    assert set(sandbox["networks"]) == {"data", "projectfs_gateway"}
    assert not sandbox.get("ports")
    assert sandbox["environment"]["SANDBOXD_NETWORK_MODE"] == "none"
    assert resolved["networks"]["data"]["internal"] is True
    assert not resolved["networks"]["projectfs_gateway"].get("internal", False)
    assert not list(tmp_path.glob("agenticos-projectfs.*"))
