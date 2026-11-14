"""Run the real Bash retention and deploy procedure against a Docker CLI fake."""

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.deploy_image_engine import Container, Engine, Image

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "scripts/deploy.sh"
BASH = shutil.which("bash") or "/bin/bash"
BACKEND = "ghcr.io/vstorm-co/agenticos-backend"
FRONTEND = "ghcr.io/vstorm-co/agenticos-frontend"
BROWSER = "ghcr.io/vstorm-co/agenticos-browser"
TARGET = "a" * 40
FUNCTIONS = (
    "release_repository",
    "image_in_list",
    "release_pin_prefix",
    "container_image_ids",
    "removable_release_refs",
    "remember_release_images",
    "prune_release_images",
    "require_image_space",
    "check_image_space",
    "record_release_images",
)


def pin(role: str, path: str = "/stack") -> str:
    data = path.encode()
    scope = hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()
    return f"deploy-{scope}-{role}"


def image(number: int, repo: str = BACKEND, *, tags: list[str] | None = None) -> Image:
    return Image(
        id=f"sha256:{number:064x}",
        created=f"2026-10-{number:02}T00:00:00Z",
        tags=tags if tags is not None else [f"{repo}:sha-{number:07x}"],
    )


class Host:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.state_path = path / "engine.json"
        binary = path / "bin"
        binary.mkdir()
        for name in ("docker", "git", "df"):
            executable = binary / name
            executable.write_text(
                f"#!{sys.executable}\nfrom tests.deploy_image_engine import fake_command\nfake_command()\n"
            )
            executable.chmod(0o700)
        self.env = {
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "PYTHONPATH": str(ROOT / "backend"),
            "RETENTION_TEST_STATE": str(self.state_path),
            "APP_DIR": str(path),
        }
        (path / "backend").mkdir()
        (path / "backend/.env").write_text("")

    def run(
        self, state: Engine, command: str, *, whole_script: bool = False
    ) -> tuple[subprocess.CompletedProcess[str], Engine]:
        self.state_path.write_text(state.model_dump_json())
        if whole_script:
            args = [BASH, str(DEPLOY), TARGET]
        else:
            source = DEPLOY.read_text()
            definitions = []
            for name in FUNCTIONS:
                match = re.search(rf"(?ms)^{name}\(\) \{{\n.*?^\}}", source)
                assert match is not None, name
                definitions.append(match[0])
            args = [BASH, "-c", "set -euo pipefail\n" + "\n".join(definitions) + "\n" + command]
        result = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=60)
        return result, Engine.model_validate_json(self.state_path.read_text())


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_old_tagged_images_are_removed_before_any_pull(host: Host) -> None:
    old = image(1)
    current = image(2)
    target = image(9, tags=[f"{BACKEND}:sha-{TARGET[:7]}"])
    frontend = image(8, FRONTEND, tags=[f"{FRONTEND}:sha-{TARGET[:7]}"])
    state = Engine(
        images=[old, current, image(3), image(4), target, frontend],
        containers=[
            Container(
                id="app", image=current.id, reference=current.tags[0], working_dir=str(host.path)
            )
        ],
        available_kib=4 * 1024 * 1024,
    )
    result, after = host.run(state, "", whole_script=True)
    assert result.returncode == 0, result.stderr
    assert old.id not in {i.id for i in after.images}, (
        "old tagged release still occupies the image store"
    )
    removal = next(n for n, c in enumerate(after.calls) if c[:3] == ["docker", "image", "rm"])
    pull = next(n for n, c in enumerate(after.calls) if "compose" in c and "pull" in c)
    assert removal < pull
    assert after.image(f"{BACKEND}:{pin('rollback', str(host.path.resolve()))}").id == current.id
    assert after.image(f"{BACKEND}:{pin('current', str(host.path.resolve()))}").id == target.id


@pytest.mark.parametrize("repo", [BACKEND, FRONTEND, BROWSER])
def test_retention_counts_image_ids_and_removes_all_immutable_aliases(
    host: Host, repo: str
) -> None:
    oldest = image(1, repo, tags=[f"{repo}:sha-0000001", f"{repo}:v1.0.1", f"{repo}:1.0.1"])
    state = Engine(images=[oldest, image(2, repo), image(3, repo)])
    result, after = host.run(state, f"prune_release_images sha-{TARGET[:7]}")
    assert result.returncode == 0, result.stderr
    assert {i.id for i in after.images} == {state.images[1].id, state.images[2].id}
    assert [c for c in after.calls if c[:3] == ["docker", "image", "rm"]] == [
        ["docker", "image", "rm", "--no-prune", *oldest.tags]
    ]


@pytest.mark.parametrize("running", [False, True])
def test_all_container_references_protect_the_entire_image(host: Host, running: bool) -> None:
    kept = image(1)
    state = Engine(
        images=[kept, image(2), image(3), image(4)],
        containers=[Container(id="other-project", image=kept.id, running=running)],
    )
    result, after = host.run(state, f"prune_release_images sha-{TARGET[:7]}")
    assert result.returncode == 0, result.stderr
    assert kept.id in {i.id for i in after.images}


@pytest.mark.parametrize(
    "alias",
    [
        f"{BACKEND}:{pin('current')}",
        f"{BACKEND}:{pin('rollback')}",
        f"{BACKEND}:latest",
        f"{BACKEND}:custom",
        "runtime/python:1.0.1",
        "ghcr.io/other/agenticos-backend:1.0.1",
    ],
)
def test_pins_and_non_release_aliases_protect_every_alias(host: Host, alias: str) -> None:
    kept = image(1, tags=[f"{BACKEND}:sha-0000001", alias])
    result, after = host.run(
        Engine(images=[kept, image(2), image(3), image(4)]),
        f"prune_release_images sha-{TARGET[:7]}",
    )
    assert result.returncode == 0, result.stderr
    assert after.image(kept.id).tags == kept.tags


def test_foreign_digest_and_untagged_runtime_images_are_not_candidates(host: Host) -> None:
    kept = image(1)
    kept.digests = ["runtime/python@sha256:other"]
    untagged = image(2, tags=[])
    result, after = host.run(
        Engine(images=[kept, untagged, image(3), image(4), image(5)]),
        f"prune_release_images sha-{TARGET[:7]}",
    )
    assert result.returncode == 0, result.stderr
    assert {kept.id, untagged.id} <= {i.id for i in after.images}


def test_target_is_protected_even_when_rolling_back_to_an_old_image(host: Host) -> None:
    target = image(1, tags=[f"{BACKEND}:sha-{TARGET[:7]}"])
    result, after = host.run(
        Engine(images=[target, image(2), image(3), image(4)]),
        f"prune_release_images sha-{TARGET[:7]}",
    )
    assert result.returncode == 0, result.stderr
    assert target.id in {i.id for i in after.images}


def test_a_container_created_after_inventory_still_protects_its_image(host: Host) -> None:
    kept = image(1)
    state = Engine(images=[kept, image(2), image(3)], late_container_image=kept.id)
    result, after = host.run(state, f"prune_release_images sha-{TARGET[:7]}")
    assert result.returncode == 0, result.stderr
    assert kept.id in {i.id for i in after.images}


@pytest.mark.parametrize(
    "failure", ["docker ps", "docker image ls", "docker image inspect", "docker image rm"]
)
def test_inventory_or_removal_failure_refuses_the_pull(host: Host, failure: str) -> None:
    state = Engine(images=[image(1), image(2), image(3)], fail=failure)
    result, after = host.run(state, f"prune_release_images sha-{TARGET[:7]}; docker compose pull")
    assert result.returncode != 0
    assert not any("pull" in call for call in after.calls)


def test_insufficient_space_stops_before_restarting_any_service(host: Host) -> None:
    result, after = host.run(Engine(available_kib=100), "", whole_script=True)
    assert result.returncode != 0
    assert "Insufficient space" in result.stderr and "5 GiB" in result.stderr
    assert not any("pull" in call or "up" in call for call in after.calls)


@pytest.mark.parametrize("available", [5242880, 5242881])
def test_space_guard_accepts_the_documented_minimum(host: Host, available: int) -> None:
    result, _ = host.run(Engine(available_kib=available), "check_image_space")
    assert result.returncode == 0, result.stderr


def test_a_failed_deployment_keeps_the_successful_pin(host: Host) -> None:
    current = image(
        1, tags=[f"{BACKEND}:sha-0000001", f"{BACKEND}:{pin('current', str(host.path.resolve()))}"]
    )
    state = Engine(images=[current], fail="docker compose")
    result, after = host.run(state, "", whole_script=True)
    assert result.returncode != 0
    assert after.image(f"{BACKEND}:{pin('current', str(host.path.resolve()))}").id == current.id


def test_a_redeploy_does_not_replace_the_rollback_with_itself(host: Host) -> None:
    previous = image(1, tags=[f"{BACKEND}:{pin('rollback')}"])
    current = image(2, tags=[f"{BACKEND}:{pin('current')}", f"{BACKEND}:sha-{TARGET[:7]}"])
    result, after = host.run(
        Engine(images=[previous, current]),
        f"record_release_images sha-{TARGET[:7]} {shlex.quote(f'{BACKEND}|{current.id}')} /stack agenticos-backend",
    )
    assert result.returncode == 0, result.stderr
    assert after.image(f"{BACKEND}:{pin('rollback')}").id == previous.id


def test_an_image_shared_by_repositories_is_kept_if_either_retains_it(host: Host) -> None:
    shared = image(1, tags=[f"{BACKEND}:sha-0000001", f"{FRONTEND}:sha-0000001"])
    result, after = host.run(
        Engine(images=[shared, image(2), image(3)]), f"prune_release_images sha-{TARGET[:7]}"
    )
    assert result.returncode == 0, result.stderr
    assert shared.id in {i.id for i in after.images}


def test_a_known_successful_pin_is_not_replaced_by_a_partial_deploy(host: Host) -> None:
    good = image(1, tags=[f"{BACKEND}:{pin('current')}"])
    partial = image(2)
    state = Engine(
        images=[good, partial],
        containers=[Container(id="app", image=partial.id, reference=partial.tags[0])],
    )
    result, after = host.run(state, "remember_release_images /stack")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{BACKEND}|{good.id}"
    assert after.image(f"{BACKEND}:{pin('current')}").id == good.id


def test_bootstrap_refuses_two_different_healthy_backend_images(host: Host) -> None:
    first, second = image(1), image(2)
    state = Engine(
        images=[first, second],
        containers=[
            Container(id="app", image=first.id, reference=first.tags[0]),
            Container(id="worker", image=second.id, reference=second.tags[0], service="worker"),
        ],
    )
    result, after = host.run(state, "remember_release_images /stack")
    assert result.returncode != 0
    assert "multiple image IDs" in result.stderr
    assert not any(c[:3] == ["docker", "image", "tag"] for c in after.calls)


@pytest.mark.parametrize("health", ["unhealthy", ""])
def test_an_unhealthy_or_unrelated_stack_is_not_bootstrapped_as_successful(
    host: Host, health: str
) -> None:
    first, second = image(1), image(2)
    state = Engine(
        images=[first, second],
        containers=[
            Container(id="bad", image=first.id, reference=first.tags[0], health=health),
            Container(id="other", image=second.id, reference=second.tags[0], working_dir="/other"),
        ],
    )
    result, after = host.run(state, "remember_release_images /stack")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""
    assert not any(c[:3] == ["docker", "image", "tag"] for c in after.calls)


def test_low_space_after_the_backend_pull_never_starts_services(host: Host) -> None:
    current = image(1, tags=[f"{BACKEND}:{pin('current', str(host.path.resolve()))}"])
    state = Engine(images=[current], available_kib=8 * 1024 * 1024, pull_cost_kib=4 * 1024 * 1024)
    result, after = host.run(state, "", whole_script=True)
    assert result.returncode != 0
    assert "Insufficient space" in result.stderr
    assert len([call for call in after.calls if "pull" in call]) == 1
    assert not any("up" in call for call in after.calls)
    assert after.image(f"{BACKEND}:{pin('current', str(host.path.resolve()))}").id == current.id


def test_failed_health_start_does_not_promote_the_target_or_overwrite_rollback(host: Host) -> None:
    previous = image(1, tags=[f"{BACKEND}:{pin('rollback', str(host.path.resolve()))}"])
    current = image(2, tags=[f"{BACKEND}:{pin('current', str(host.path.resolve()))}"])
    state = Engine(images=[previous, current], fail_up=True)
    result, after = host.run(state, "", whole_script=True)
    assert result.returncode != 0
    assert after.image(f"{BACKEND}:{pin('current', str(host.path.resolve()))}").id == current.id
    assert after.image(f"{BACKEND}:{pin('rollback', str(host.path.resolve()))}").id == previous.id


@pytest.mark.parametrize("failure", ["docker info", "df"])
def test_capacity_inventory_failure_is_an_error(host: Host, failure: str) -> None:
    result, after = host.run(Engine(fail=failure), "check_image_space; docker compose pull")
    assert result.returncode != 0
    assert not any("pull" in call for call in after.calls)


def test_stacks_sharing_repositories_keep_separate_current_and_rollback_pins(host: Host) -> None:
    other = image(1, tags=[f"{BACKEND}:{pin('current', '/other')}"])
    current = image(2)
    target = image(3, tags=[f"{BACKEND}:sha-{TARGET[:7]}"])
    state = Engine(
        images=[other, current, target, image(4), image(5), image(6)],
        containers=[Container(id="app", image=current.id, reference=current.tags[0])],
    )
    result, after = host.run(
        state,
        f'previous=$(remember_release_images /stack); record_release_images sha-{TARGET[:7]} "$previous" /stack agenticos-backend; prune_release_images sha-{TARGET[:7]}',
    )
    assert result.returncode == 0, result.stderr
    assert after.image(f"{BACKEND}:{pin('current', '/other')}").id == other.id
    assert after.image(f"{BACKEND}:{pin('current')}").id == target.id
    assert after.image(f"{BACKEND}:{pin('rollback')}").id == current.id


@pytest.mark.parametrize("fractions", [("", ".001", ".002"), (".1", ".12", ".2")])
def test_newest_retention_compares_fractional_creation_times_chronologically(
    host: Host, fractions: tuple[str, str, str]
) -> None:
    images = [image(1), image(2), image(3)]
    for item, fraction in zip(images, fractions, strict=True):
        item.created = f"2026-11-10T01:00:00{fraction}Z"
    result, after = host.run(Engine(images=images), f"prune_release_images sha-{TARGET[:7]}")
    assert result.returncode == 0, result.stderr
    assert {i.id for i in after.images} == {images[1].id, images[2].id}


def test_an_unknown_creation_timestamp_refuses_to_guess_retention_order(host: Host) -> None:
    unknown = image(1)
    unknown.created = "not-a-timestamp"
    result, after = host.run(
        Engine(images=[unknown, image(2), image(3)]), f"prune_release_images sha-{TARGET[:7]}"
    )
    assert result.returncode != 0
    assert "unsupported creation timestamp" in result.stderr
    assert {i.id for i in after.images} == {unknown.id, image(2).id, image(3).id}


def test_removing_a_release_never_implicitly_prunes_its_untagged_parent(host: Host) -> None:
    runtime_parent = image(1, tags=[])
    release = image(2)
    release.parent = runtime_parent.id
    result, after = host.run(
        Engine(images=[runtime_parent, release, image(3), image(4)]),
        f"prune_release_images sha-{TARGET[:7]}",
    )
    assert result.returncode == 0, result.stderr
    assert release.id not in {i.id for i in after.images}
    assert runtime_parent.id in {i.id for i in after.images}


def test_desktop_checks_vm_capacity_without_treating_its_path_as_a_host_path(host: Host) -> None:
    state = Engine(images=[image(1)], operating_system="Docker Desktop", root="/inside-the-vm")
    result, after = host.run(state, "check_image_space")
    assert result.returncode == 0, result.stderr
    [probe] = [call for call in after.calls if call[:2] == ["docker", "run"]]
    assert {"--rm", "--pull=never", "--read-only", "--network=none", "--cap-drop=ALL"} <= set(probe)
    assert probe[-4:] == ["df", state.images[0].id, "-Pk", "/"]
    assert ["df", "-Pk", str(host.path)] in after.calls
    assert not any(call[0] == "df" and state.root in call for call in after.calls)


@pytest.mark.parametrize("vm_low", [True, False])
def test_desktop_refuses_insufficient_vm_or_host_capacity(host: Host, vm_low: bool) -> None:
    state = Engine(
        images=[image(1)],
        operating_system="Docker Desktop",
        available_kib=100 if vm_low else 10 * 1024 * 1024,
        host_available_kib=10 * 1024 * 1024 if vm_low else 100,
    )
    result, after = host.run(state, "check_image_space; docker compose pull")
    assert result.returncode != 0
    assert "Insufficient space" in result.stderr
    assert ("Docker Desktop VM" if vm_low else str(host.path)) in result.stderr
    assert not any("pull" in call for call in after.calls)


def test_desktop_does_not_download_a_probe_image_on_first_installation(host: Host) -> None:
    result, after = host.run(Engine(operating_system="Docker Desktop"), "check_image_space")
    assert result.returncode != 0
    assert "cached AgenticOS backend image" in result.stderr
    assert not any("pull" in call or "run" in call for call in after.calls)


def test_a_failed_desktop_storage_probe_refuses_to_guess_capacity(host: Host) -> None:
    state = Engine(images=[image(1)], operating_system="Docker Desktop", fail="docker run")
    result, after = host.run(state, "check_image_space; docker compose pull")
    assert result.returncode != 0
    assert not any("pull" in call for call in after.calls)


def test_desktop_probe_uses_the_known_healthy_backend_instead_of_another_cached_build(
    host: Host,
) -> None:
    cached, healthy = image(1), image(2)
    state = Engine(images=[cached, healthy], operating_system="Docker Desktop")
    result, after = host.run(state, f"check_image_space {shlex.quote(f'{BACKEND}|{healthy.id}')}")
    assert result.returncode == 0, result.stderr
    [probe] = [call for call in after.calls if call[:2] == ["docker", "run"]]
    assert probe[-3] == healthy.id


def test_desktop_fallback_probe_never_selects_an_unrelated_repository(host: Host) -> None:
    unrelated, backend = image(1, "runtime/python"), image(2)
    state = Engine(images=[unrelated, backend], operating_system="Docker Desktop")
    result, after = host.run(state, "check_image_space")
    assert result.returncode == 0, result.stderr
    [probe] = [call for call in after.calls if call[:2] == ["docker", "run"]]
    assert probe[-3] == backend.id


def test_a_symlink_stack_path_keeps_its_existing_compose_identity_and_rollback(host: Host) -> None:
    link = host.path / "stack-link"
    link.symlink_to(host.path, target_is_directory=True)
    host.env["APP_DIR"] = str(link)
    current = image(1)
    target = image(2, tags=[f"{BACKEND}:sha-{TARGET[:7]}"])
    frontend = image(3, tags=[f"{FRONTEND}:sha-{TARGET[:7]}"])
    state = Engine(
        images=[current, target, frontend],
        containers=[
            Container(id="app", image=current.id, reference=current.tags[0], working_dir=str(link))
        ],
    )
    result, after = host.run(state, "", whole_script=True)
    assert result.returncode == 0, result.stderr
    assert after.image(f"{BACKEND}:{pin('rollback', str(link))}").id == current.id
    assert after.image(f"{BACKEND}:{pin('current', str(link))}").id == target.id
