"""The production stack can turn a visual into an image without public browser access."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_the_production_renderer_is_isolated_and_reachable_by_both_runners() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose-prod.yml").read_text())
    services = compose["services"]
    renderer = services["visual-render"]
    assert renderer["profiles"] == ["visuals"]
    assert renderer["networks"] == ["visuals"]
    assert not renderer.get("ports")
    assert compose["networks"]["visuals"]["internal"] is True
    for service in ("app", "worker"):
        assert "visuals" in services[service]["networks"]
    assert services["db"]["networks"] == ["data"]


@pytest.mark.parametrize(
    ("endpoint", "enabled"),
    [
        ("http://visual-render:9222", True),
        ("http://visual-render:9222/", True),
        ("", False),
        ("https://external-browser.example.com", False),
    ],
)
def test_deploy_preserves_the_renderer_profile_without_losing_the_sandbox(
    endpoint: str, enabled: bool
) -> None:
    source = (ROOT / "scripts/deploy.sh").read_text()
    start = source.index('case "$(env_value VISUAL_RENDER_CDP_URL)" in')
    end = source.index("esac", start) + len("esac")
    script = (
        "PROFILES=(--profile sandbox)\n"
        + source[start:end].replace("$(env_value VISUAL_RENDER_CDP_URL)", "$1")
        + '\nprintf "%s\\n" "${PROFILES[@]}"\n'
    )
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", script, "profile-test", endpoint],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    expected = ["--profile", "sandbox"] + (["--profile", "visuals"] if enabled else [])
    assert result.stdout.splitlines() == expected


def test_published_backend_images_include_the_visual_rendering_client() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/images.yml").read_text())
    builds = [
        step["with"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Build and push by digest"
    ]
    assert len(builds) == 1
    assert "matrix.image == 'backend'" in builds[0]["build-args"]
    assert "EXTRAS=--extra browser" in builds[0]["build-args"]


@pytest.mark.parametrize("enabled", [True, False])
def test_deploy_waits_for_the_renderer_manifest_only_when_enabled(enabled: bool) -> None:
    source = (ROOT / "scripts/deploy.sh").read_text()
    start = source.index("IMAGES=(agenticos-backend agenticos-frontend)")
    end = source.index('for image in "${IMAGES[@]}"', start)
    script = source[start:end] + '\nprintf "%s\\n" "${IMAGES[@]}"'
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={"VISUAL_RENDERER": "true" if enabled else "false", "INTERACTIVE_BROWSER": "false"},
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    expected = ["agenticos-backend", "agenticos-frontend"]
    if enabled:
        expected.append("agenticos-browser")
    assert result.stdout.splitlines() == expected


def test_deploy_checks_cdp_readiness_before_reporting_success() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose-prod.yml").read_text())
    health = compose["services"]["visual-render"]["healthcheck"]
    assert "GET /json/version HTTP/1.1" in health["test"][-1]
    assert "webSocketDebuggerUrl" in health["test"][-1]
    assert health["start_period"] == "30s"
    script = (ROOT / "scripts/deploy.sh").read_text()
    readiness = script[script.index('say "Waiting for health"') :]
    assert 'if "$VISUAL_RENDERER"; then' in readiness
    assert 'wait_healthy visual-render "${BACKEND[@]}" "${PROFILES[@]}"' in readiness
    assert readiness.index("wait_healthy visual-render") < readiness.index('say "Deployed')


def test_interactive_browser_has_only_proxy_egress_and_is_separate_from_renderer():
    compose = yaml.safe_load((ROOT / "docker-compose-prod.yml").read_text())
    services = compose["services"]
    assert services["browser"]["networks"] == ["browser"]
    assert compose["networks"]["browser"]["internal"] is True
    assert set(services["browser-egress"]["networks"]) == {"browser", "browser-egress"}
    assert not services["browser"].get("ports")
    assert "TZ=${BROWSER_TZ:-UTC}" in services["browser"]["environment"]
    assert "BROWSER_LANG=${BROWSER_LANG:-en-US}" in services["browser"]["environment"]
    assert services["visual-render"]["networks"] == ["visuals"]
    for runner in ("app", "worker"):
        assert "browser" in services[runner]["networks"]


def test_interactive_browser_waits_for_a_working_proxy():
    services = yaml.safe_load((ROOT / "docker-compose-prod.yml").read_text())["services"]
    assert services["browser"]["depends_on"]["browser-egress"]["condition"] == "service_healthy"
    assert "grep -q '403'" in services["browser-egress"]["healthcheck"]["test"][-1]
    assert "wait_healthy browser-egress" in (ROOT / "scripts/deploy.sh").read_text()
