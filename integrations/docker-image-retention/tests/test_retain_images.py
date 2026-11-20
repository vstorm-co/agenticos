"""Synthetic Docker inventories exercise retention without contacting a daemon."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "retain_images.py"
MODULE_SPEC = importlib.util.spec_from_file_location("retain_images", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
retention = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = retention
MODULE_SPEC.loader.exec_module(retention)

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
REPOSITORY = "registry.example.test/demo/api"
OTHER_REPOSITORY = "registry.example.test/unrelated/api"
PROJECT = "synthetic-demo"
DAEMON = "synthetic-daemon-id"


def image_id(number: int) -> str:
    return f"sha256:{number:064x}"


def image(
    number: int,
    *,
    age_days: int = 30,
    repository: str = REPOSITORY,
    tags: tuple[str, ...] | None = None,
    digests: tuple[str, ...] | None = None,
) -> retention.Image:
    return retention.Image(
        image_id=image_id(number),
        created=NOW - timedelta(days=age_days),
        repo_tags=tags if tags is not None else (f"{repository}:release-{number}",),
        repo_digests=digests if digests is not None else (f"{repository}@sha256:{number + 1000:064x}",),
        size_bytes=1000,
    )


def container(
    number: int,
    image_number: int,
    *,
    project: str | None = PROJECT,
    service: str | None = "api",
    running: bool = True,
    status: str | None = None,
    health: str | None = "healthy",
    configured_image: str | None = None,
) -> retention.Container:
    return retention.Container(
        container_id=f"{number:064x}",
        image_id=image_id(image_number),
        configured_image=configured_image or f"{REPOSITORY}:release-{image_number}",
        project=project,
        service=service,
        running=running,
        status=status or ("running" if running else "exited"),
        health=health,
    )


def policy_document(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "docker_host": "unix:///var/run/docker.sock",
        "daemon_id": DAEMON,
        "compose_project": PROJECT,
        "lock_file": "/var/lib/synthetic-demo/deploy.lock",
        "repositories": [REPOSITORY],
        "components": {
            "api": {
                "repository": REPOSITORY,
                "current_image_id": image_id(1),
                "previous_successful_image_id": image_id(2),
            },
        },
        **overrides,
    }


def policy(**overrides: object) -> retention.Policy:
    return retention.parse_policy(policy_document(**overrides))


def snapshot(
    *extra_images: retention.Image,
    containers: tuple[retention.Container, ...] | None = None,
) -> retention.Snapshot:
    images = (image(1), image(2), *extra_images)
    return retention.Snapshot(
        info=retention.DaemonInfo(daemon_id=DAEMON, docker_root_dir=Path("/var/lib/docker")),
        images={entry.image_id: entry for entry in images},
        containers=containers if containers is not None else (container(100, 1),),
    )


class FakeDocker(retention.DockerClient):
    def __init__(self, state: retention.Snapshot) -> None:
        self.state = state
        self.removed: list[str] = []
        self.attempted: list[str] = []
        self.snapshot_calls = 0
        self.before_snapshot: Callable[[FakeDocker], None] | None = None
        self.fail_on: str | None = None
        self.leave_image_behind = False

    def info(self) -> retention.DaemonInfo:
        return self.state.info

    def snapshot(self) -> retention.Snapshot:
        self.snapshot_calls += 1
        if self.before_snapshot is not None:
            self.before_snapshot(self)
        return self.state

    def remove_image(self, target_id: str) -> None:
        self.attempted.append(target_id)
        if target_id == self.fail_on:
            raise retention.RetentionError("Synthetic Docker refusal")
        self.removed.append(target_id)
        if not self.leave_image_behind:
            self.state = replace(
                self.state,
                images={key: value for key, value in self.state.images.items() if key != target_id},
            )


class PlanningTests(unittest.TestCase):
    def test_only_old_unreferenced_owned_images_are_candidates(self) -> None:
        old = image(3)
        state = snapshot(old, image(4, age_days=2), image(5, repository=OTHER_REPOSITORY))
        plan = retention.plan_images(policy(), state, NOW)
        self.assertEqual(tuple(entry.image_id for entry in plan.candidates), (old.image_id,))
        self.assertEqual(plan.protected_ids, frozenset({image_id(1), image_id(2)}))

    def test_stopped_containers_protect_images_even_outside_the_configured_project(self) -> None:
        state = snapshot(
            image(3),
            containers=(container(100, 1), container(101, 3, project="other-project", running=False)),
        )
        plan = retention.plan_images(policy(), state, NOW)
        self.assertEqual(plan.candidates, ())
        self.assertIn(image_id(3), plan.protected_ids)

    def test_an_unrelated_running_containers_image_is_protected(self) -> None:
        state = snapshot(
            image(3, repository=OTHER_REPOSITORY),
            containers=(
                container(100, 1),
                container(101, 3, project="other-project", configured_image=f"{OTHER_REPOSITORY}:release-3"),
            ),
        )
        plan = retention.plan_images(policy(), state, NOW)
        self.assertIn(image_id(3), plan.protected_ids)
        self.assertEqual(plan.candidates, ())

    def test_unused_previous_successful_release_and_all_its_aliases_are_protected(self) -> None:
        rollback = image(2, tags=(f"{REPOSITORY}:old", f"{REPOSITORY}:rollback", f"{OTHER_REPOSITORY}:shared"))
        state = snapshot(rollback, image(3))
        plan = retention.plan_images(policy(), state, NOW)
        self.assertIn(image_id(2), plan.protected_ids)
        self.assertEqual(tuple(entry.image_id for entry in plan.candidates), (image_id(3),))

    def test_ownership_checks_every_tag_and_digest_and_exact_repository(self) -> None:
        cases = {
            "foreign tag": image(3, tags=(f"{OTHER_REPOSITORY}:foreign",)),
            "foreign digest": image(3, digests=(f"{OTHER_REPOSITORY}@sha256:{3000:064x}",)),
            "extra digest": image(
                3,
                digests=(f"{REPOSITORY}@sha256:{3000:064x}", f"{OTHER_REPOSITORY}@sha256:{4000:064x}"),
            ),
            "similar repository": image(3, repository=REPOSITORY + "-other"),
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                self.assertEqual(retention.plan_images(policy(), snapshot(candidate), NOW).candidates, ())

    def test_unknown_dangling_ownership_and_multiple_tags_are_never_removed(self) -> None:
        for candidate in (
            image(3, tags=(), digests=()),
            image(3, tags=("<none>:<none>",), digests=()),
            image(3, tags=(f"{REPOSITORY}:one", f"{REPOSITORY}:two")),
        ):
            with self.subTest(tags=candidate.repo_tags):
                self.assertEqual(retention.plan_images(policy(), snapshot(candidate), NOW).candidates, ())

    def test_a_digest_only_owned_image_can_be_considered_without_treating_digest_as_image_id(self) -> None:
        candidate = image(3, tags=())
        plan = retention.plan_images(policy(), snapshot(candidate), NOW)
        self.assertEqual(tuple(entry.image_id for entry in plan.candidates), (image_id(3),))
        self.assertNotEqual(candidate.image_id, candidate.repo_digests[0].split("@", 1)[1])

    def test_young_and_future_images_are_retained(self) -> None:
        plan = retention.plan_images(policy(), snapshot(image(3, age_days=6), image(4, age_days=-1)), NOW)
        self.assertEqual(plan.candidates, ())

    def test_removal_cap_chooses_oldest_eligible_images_first(self) -> None:
        plan = retention.plan_images(
            policy(max_removals=2),
            snapshot(image(3, age_days=8), image(4, age_days=20), image(5, age_days=60)),
            NOW,
        )
        self.assertEqual(tuple(entry.image_id for entry in plan.candidates), (image_id(5), image_id(4)))
        self.assertEqual(plan.eligible_count, 3)

    def test_missing_current_or_rollback_config_id_refuses_the_whole_plan(self) -> None:
        for missing_id in (image_id(1), image_id(2)):
            with self.subTest(missing_id=missing_id):
                state = snapshot(image(3))
                state = replace(state, images={key: value for key, value in state.images.items() if key != missing_id})
                with self.assertRaises(retention.RetentionError):
                    retention.plan_images(policy(), state, NOW)

    def test_a_registry_manifest_digest_cannot_substitute_for_a_pin(self) -> None:
        config = policy_document()
        config["components"] = {
            "api": {
                "repository": REPOSITORY,
                "current_image_id": image_id(1001),
                "previous_successful_image_id": image_id(2),
            },
        }
        with self.assertRaises(retention.RetentionError):
            retention.plan_images(retention.parse_policy(config), snapshot(image(3)), NOW)

    def test_a_pin_must_belong_to_its_configured_repository(self) -> None:
        for number in (1, 2):
            with self.subTest(number=number), self.assertRaises(retention.RetentionError):
                retention.plan_images(policy(), snapshot(image(number, repository=OTHER_REPOSITORY), image(3)), NOW)

    def test_current_release_requires_running_healthy_exact_project_and_service(self) -> None:
        for current in (
            container(100, 1, running=False),
            container(100, 1, health=None),
            container(100, 1, health="starting"),
            container(100, 1, health="unhealthy"),
            container(100, 1, project="different-project"),
            container(100, 1, service="different-service"),
            container(100, 1, status="paused"),
        ):
            with self.subTest(current=current), self.assertRaises(retention.RetentionError):
                retention.plan_images(policy(), snapshot(image(3), containers=(current,)), NOW)

    def test_unexpected_active_release_in_a_managed_repository_refuses_cleanup(self) -> None:
        for extra in (
            container(101, 3),
            container(101, 3, project="different-project"),
            container(101, 3, service="unexpected-service"),
        ):
            with self.subTest(extra=extra), self.assertRaises(retention.RetentionError):
                retention.plan_images(policy(), snapshot(image(3), containers=(container(100, 1), extra)), NOW)

    def test_current_pins_are_required_for_every_configured_component(self) -> None:
        config = policy_document()
        config["components"] = {
            "api": {
                "repository": REPOSITORY,
                "current_image_id": image_id(1),
                "previous_successful_image_id": image_id(2),
            },
            "worker": {
                "repository": REPOSITORY,
                "current_image_id": image_id(1),
                "previous_successful_image_id": image_id(2),
            },
        }
        configured = retention.parse_policy(config)
        with self.assertRaises(retention.RetentionError):
            retention.plan_images(configured, snapshot(image(3)), NOW)
        healthy = snapshot(image(3), containers=(container(100, 1), container(101, 1, service="worker")))
        plan = retention.plan_images(configured, healthy, NOW)
        self.assertEqual(tuple(entry.image_id for entry in plan.candidates), (image_id(3),))

    def test_daemon_identity_mismatch_refuses_the_plan(self) -> None:
        state = snapshot(image(3))
        state = replace(state, info=replace(state.info, daemon_id="a-different-daemon"))
        with self.assertRaises(retention.RetentionError):
            retention.plan_images(policy(), state, NOW)


class ApplyTests(unittest.TestCase):
    def test_apply_removes_only_the_capped_plan_and_preserves_pins(self) -> None:
        configured = policy(max_removals=1)
        initial = snapshot(image(3, age_days=20), image(4, age_days=10))
        plan = retention.plan_images(configured, initial, NOW)
        docker = FakeDocker(initial)
        removed = retention.apply_plan(configured, initial, plan, docker, NOW)
        self.assertEqual(removed, (image_id(3),))
        self.assertEqual(set(docker.state.images), {image_id(1), image_id(2), image_id(4)})

    def test_a_new_stopped_container_reference_aborts_before_any_deletion(self) -> None:
        initial = snapshot(image(3))
        changed = replace(initial, containers=(*initial.containers, container(101, 3, running=False)))
        docker = FakeDocker(changed)
        with self.assertRaises(retention.RetentionError):
            retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
        self.assertEqual(docker.attempted, [])

    def test_a_changed_alias_or_missing_candidate_aborts_before_any_deletion(self) -> None:
        initial = snapshot(image(3))
        for images in (
            {**initial.images, image_id(3): image(3, tags=(f"{OTHER_REPOSITORY}:new-owner",))},
            {key: value for key, value in initial.images.items() if key != image_id(3)},
        ):
            docker = FakeDocker(replace(initial, images=images))
            with self.subTest(images=images), self.assertRaises(retention.RetentionError):
                retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
            self.assertEqual(docker.attempted, [])

    def test_protected_metadata_and_daemon_root_changes_abort_before_deletion(self) -> None:
        initial = snapshot(image(3))
        cases = (
            replace(
                initial,
                images={**initial.images, image_id(2): image(2, tags=(f"{REPOSITORY}:new-rollback-alias",))},
            ),
            replace(initial, info=replace(initial.info, docker_root_dir=Path("/another/docker-root"))),
            replace(initial, info=replace(initial.info, daemon_id="another-daemon")),
        )
        for changed in cases:
            docker = FakeDocker(changed)
            with self.subTest(changed=changed), self.assertRaises(retention.RetentionError):
                retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
            self.assertEqual(docker.attempted, [])

    def test_each_removal_rechecks_drift_and_reports_prior_successes(self) -> None:
        initial = snapshot(image(3, age_days=30), image(4, age_days=20))
        docker = FakeDocker(initial)

        def start_another_container(client: FakeDocker) -> None:
            if client.snapshot_calls == 3:
                client.state = replace(
                    client.state,
                    containers=(*client.state.containers, container(101, 4, running=False)),
                )

        docker.before_snapshot = start_another_container
        with self.assertRaises(retention.RetentionError) as caught:
            retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
        self.assertEqual(docker.attempted, [image_id(3)])
        self.assertEqual(caught.exception.removed_image_ids, (image_id(3),))
        self.assertIn(image_id(4), docker.state.images)

    def test_docker_refusal_stops_without_trying_the_next_candidate(self) -> None:
        initial = snapshot(image(3, age_days=30), image(4, age_days=20))
        docker = FakeDocker(initial)
        docker.fail_on = image_id(3)
        with self.assertRaises(retention.RetentionError):
            retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
        self.assertEqual(docker.attempted, [image_id(3)])
        self.assertEqual(docker.removed, [])

    def test_a_successful_command_that_did_not_remove_the_image_is_not_counted_as_success(self) -> None:
        initial = snapshot(image(3))
        docker = FakeDocker(initial)
        docker.leave_image_behind = True
        with self.assertRaises(retention.RetentionError) as caught:
            retention.apply_plan(policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW)
        self.assertEqual(caught.exception.removed_image_ids, ())
        self.assertIn(image_id(3), docker.state.images)

    def test_policy_revalidation_failure_prevents_the_docker_mutation(self) -> None:
        initial = snapshot(image(3))
        docker = FakeDocker(initial)

        def policy_changed() -> None:
            raise retention.RetentionError("Synthetic policy changed")

        with self.assertRaises(retention.RetentionError):
            retention.apply_plan(
                policy(), initial, retention.plan_images(policy(), initial, NOW), docker, NOW,
                before_delete=policy_changed,
            )
        self.assertEqual(docker.attempted, [])


class PolicyTests(unittest.TestCase):
    def test_optional_limits_have_conservative_defaults(self) -> None:
        configured = policy()
        self.assertEqual((configured.minimum_age_days, configured.max_removals), (7, 10))
        self.assertEqual((configured.min_free_gib, configured.min_free_percent), (20, 20))

    def test_remote_hosts_unknown_fields_and_unsafe_values_are_refused(self) -> None:
        for overrides in (
            {"docker_host": "tcp://127.0.0.1:2375"},
            {"docker_host": "ssh://example.test"},
            {"docker_host": "unix://relative.sock"},
            {"schema_version": 2},
            {"max_removals": True},
            {"max_removals": 0},
            {"minimum_age_days": -1},
            {"min_free_percent": 101},
            {"repositories": [REPOSITORY + "*"]},
            {"repositories": [REPOSITORY, OTHER_REPOSITORY]},
            {"lock_file": "relative.lock"},
            {"unknown_option": True},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(retention.RetentionError):
                policy(**overrides)

    def test_missing_pins_short_image_ids_and_unknown_component_fields_are_refused(self) -> None:
        valid_component = {
            "repository": REPOSITORY,
            "current_image_id": image_id(1),
            "previous_successful_image_id": image_id(2),
        }
        for component in (
            {key: value for key, value in valid_component.items() if key != "previous_successful_image_id"},
            {**valid_component, "current_image_id": "sha256:1234"},
            {**valid_component, "current_image_id": f"{REPOSITORY}@{image_id(1)}"},
            {**valid_component, "extra": "unrecognized"},
        ):
            with self.subTest(component=component), self.assertRaises(retention.RetentionError):
                policy(components={"api": component})

    def test_policy_file_must_be_private_regular_and_not_a_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(policy_document()), encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(retention.load_policy(path), policy())
            path.chmod(0o644)
            with self.assertRaises(retention.RetentionError):
                retention.load_policy(path)
            path.chmod(0o600)
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(retention.RetentionError):
                retention.load_policy(link)
            with self.assertRaises(retention.RetentionError):
                retention.load_policy(Path(directory))

    def test_duplicate_keys_and_non_finite_json_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            valid = json.dumps(policy_document())
            for text in (
                valid[:-1] + ', "schema_version": 1}',
                valid[:-1] + ', "min_free_gib": NaN}',
                valid[:-1] + ', "min_free_gib": Infinity}',
            ):
                path.write_text(text, encoding="utf-8")
                path.chmod(0o600)
                with self.subTest(text=text), self.assertRaises(retention.RetentionError):
                    retention.load_policy(path)


@unittest.skipUnless(sys.platform == "linux", "The helper's deployment lock is Linux flock")
class LockAndDockerTests(unittest.TestCase):
    docker_host = "unix:///synthetic/docker.sock"

    def client(self) -> retention.DockerClient:
        socket_stat = os.stat_result((stat.S_IFSOCK | 0o600, 0, 0, 1, os.geteuid(), os.getegid(), 0, 0, 0, 0))
        with patch.object(retention.Path, "stat", return_value=socket_stat):
            return retention.DockerClient(policy(docker_host=self.docker_host))

    def test_deployment_lock_refuses_contention_then_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deploy.lock"
            with retention.deployment_lock(path) as descriptor:
                retention.verify_lock(descriptor, path)
                with self.assertRaises(retention.RetentionError), retention.deployment_lock(path):
                    self.fail("A second process must not acquire the held deployment lock")
            with retention.deployment_lock(path) as descriptor:
                retention.verify_lock(descriptor, path)

    def test_replacing_the_lock_file_is_detected_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deploy.lock"
            with retention.deployment_lock(path) as descriptor:
                path.unlink()
                path.write_text("replacement", encoding="utf-8")
                path.chmod(0o600)
                with self.assertRaises(retention.RetentionError):
                    retention.verify_lock(descriptor, path)

    def test_removal_uses_full_config_id_no_prune_and_never_force(self) -> None:
        client = self.client()
        with patch.object(client, "_run", return_value="Deleted: " + image_id(3)) as run:
            client.remove_image(image_id(3))
        self.assertEqual(run.call_args.args, ("image", "rm", "--no-prune", image_id(3)))

    def test_nonzero_docker_command_and_invalid_info_are_failures(self) -> None:
        client = self.client()
        failure = subprocess.CompletedProcess(args=["docker"], returncode=1, stdout="", stderr="synthetic failure")
        with (
            patch.object(retention.subprocess, "run", return_value=failure),
            self.assertRaises(retention.RetentionError),
        ):
            client.info()
        invalid_info = (
            "not json", "[]", "{}",
            '{"ID": "different", "DockerRootDir": "/var/lib/docker", "OSType": "linux"}',
        )
        for text in invalid_info:
            with (
                self.subTest(text=text),
                patch.object(client, "_run", return_value=text),
                self.assertRaises(retention.RetentionError),
            ):
                client.info()

    def test_docker_host_is_explicit_and_remote_environment_cannot_redirect_commands(self) -> None:
        client = self.client()
        success = subprocess.CompletedProcess(args=["docker"], returncode=0, stdout="ok", stderr="")
        with (
            patch.dict(os.environ, {"DOCKER_HOST": "ssh://other-host", "DOCKER_CONTEXT": "remote"}),
            patch.object(retention.subprocess, "run", return_value=success) as run,
        ):
            self.assertEqual(client._run("version"), "ok")
        argv = run.call_args.args[0]
        self.assertIn("--host", argv)
        self.assertEqual(argv[argv.index("--host") + 1], self.docker_host)
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("DOCKER_HOST", environment)
        self.assertNotIn("DOCKER_CONTEXT", environment)

    def test_invalid_or_partial_image_inspection_is_not_a_successful_inventory(self) -> None:
        client = self.client()
        info = json.dumps({"ID": DAEMON, "DockerRootDir": "/var/lib/docker", "OSType": "linux"})
        valid_image = {
            "Id": image_id(1),
            "Created": "2026-10-01T12:00:00Z",
            "RepoTags": [f"{REPOSITORY}:release-1"],
            "RepoDigests": [f"{REPOSITORY}@sha256:{1001:064x}"],
            "Size": 1000,
        }
        for inspection in (
            "not JSON",
            "[]",
            json.dumps([{key: value for key, value in valid_image.items() if key != "RepoDigests"}]),
            json.dumps([{**valid_image, "Id": image_id(2)}]),
            json.dumps([{**valid_image, "Created": "2026-10-01T12:00:00"}]),
        ):
            def response(*args: str) -> str:
                if args[0] == "info":
                    return info
                if args[:2] == ("image", "ls"):
                    return image_id(1) + "\n"
                if args[:2] == ("image", "inspect"):
                    return inspection
                if args[:2] == ("container", "ls"):
                    return ""
                raise AssertionError(f"Unexpected Docker command: {args}")

            with self.subTest(inspection=inspection), patch.object(client, "_run", side_effect=response):
                with self.assertRaises(retention.RetentionError):
                    client.snapshot()


class DiskUsage(NamedTuple):
    total: int
    used: int
    free: int


class DiskAndCliTests(unittest.TestCase):
    def test_space_guard_requires_both_absolute_and_percentage_minima(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            info = retention.DaemonInfo(DAEMON, Path(directory))
            for total_gib, free_gib, sufficient in ((100, 20, True), (200, 30, False), (50, 19, False), (50, 25, True)):
                usage = DiskUsage(total_gib * 2**30, (total_gib - free_gib) * 2**30, free_gib * 2**30)
                with self.subTest(total_gib=total_gib, free_gib=free_gib):
                    with patch.object(retention.shutil, "disk_usage", return_value=usage):
                        report = retention.disk_space(policy(), info)
                    self.assertEqual(report["sufficient"], sufficient)
                    self.assertEqual(report["minimum_free_bytes"], 20 * 2**30)
                    self.assertEqual(report["minimum_free_percent"], 20)

    def test_unavailable_or_invalid_disk_measurements_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            info = retention.DaemonInfo(DAEMON, Path(directory))
            for usage in (DiskUsage(0, 0, 0), DiskUsage(100, 0, 101), DiskUsage(100, 101, -1)):
                with self.subTest(usage=usage), patch.object(retention.shutil, "disk_usage", return_value=usage):
                    with self.assertRaises(retention.RetentionError):
                        retention.disk_space(policy(), info)
            with patch.object(retention.shutil, "disk_usage", side_effect=OSError("unavailable")):
                with self.assertRaises(retention.RetentionError):
                    retention.disk_space(policy(), info)
            with self.assertRaises(retention.RetentionError):
                retention.disk_space(policy(), retention.DaemonInfo(DAEMON, Path(directory) / "absent"))

    def test_default_cli_reports_the_plan_without_removing_anything(self) -> None:
        docker = FakeDocker(snapshot(image(3)))
        output = io.StringIO()
        with (
            patch.object(retention, "load_policy", return_value=policy()),
            patch.object(retention, "DockerClient", return_value=docker),
            patch.object(retention, "disk_space", return_value={"sufficient": False}),
            patch.object(
                retention, "deployment_lock", side_effect=AssertionError("dry-run cannot acquire a mutation lock"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(retention.main(["--policy", "/synthetic-policy.json"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual([entry["image_id"] for entry in report["planned_removals"]], [image_id(3)])
        self.assertEqual(report["removed_image_ids"], [])
        self.assertEqual(docker.attempted, [])

    def test_predeploy_guard_returns_nonzero_for_low_space_and_never_inventories_or_removes_images(self) -> None:
        for enough_space, expected_code in ((True, 0), (False, 3)):
            docker = FakeDocker(snapshot(image(3)))
            with (
                self.subTest(enough_space=enough_space),
                patch.object(retention, "load_policy", return_value=policy()),
                patch.object(retention, "DockerClient", return_value=docker),
                patch.object(retention, "disk_space", return_value={"sufficient": enough_space}),
                patch.object(
                    retention, "deployment_lock", side_effect=AssertionError("the deployer may already hold this lock"),
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(retention.main(["--policy", "/synthetic-policy.json", "--check-space"]), expected_code)
            self.assertEqual(docker.snapshot_calls, 0)
            self.assertEqual(docker.attempted, [])

    def test_cli_errors_are_nonzero_and_do_not_claim_a_deletion(self) -> None:
        error = io.StringIO()
        with (
            patch.object(retention, "load_policy", side_effect=retention.RetentionError("Synthetic invalid policy")),
            redirect_stderr(error),
        ):
            self.assertEqual(
                retention.main(["--policy", "/synthetic-policy.json", "--apply", "--writers-coordinated"]), 2,
            )
        report = json.loads(error.getvalue())
        self.assertEqual(report["status"], "refused")
        self.assertEqual(report["removed_image_ids"], [])

    def test_writer_coordination_acknowledgment_is_required_for_apply_and_refused_in_read_only_modes(self) -> None:
        for arguments in (
            ["--apply"],
            ["--writers-coordinated"],
            ["--check-space", "--writers-coordinated"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(retention, "load_policy", side_effect=AssertionError("invalid flags must stop immediately")),
                patch.object(retention, "DockerClient", side_effect=AssertionError("invalid flags must not reach Docker")),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as caught,
            ):
                retention.main(["--policy", "/synthetic-policy.json", *arguments])
            self.assertEqual(caught.exception.code, 2)

    @unittest.skipUnless(sys.platform == "linux", "The helper's deployment lock is Linux flock")
    def test_apply_cli_holds_the_shared_deployment_lock_through_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "deploy.lock"
            configured = policy(lock_file=str(lock_path))
            docker = FakeDocker(snapshot(image(3)))
            remove = docker.remove_image

            def remove_while_locked(target_id: str) -> None:
                with self.assertRaises(retention.RetentionError), retention.deployment_lock(lock_path):
                    self.fail("The deletion must run under the shared deployment lock")
                remove(target_id)

            with (
                patch.object(retention, "load_policy", return_value=configured),
                patch.object(retention, "DockerClient", return_value=docker),
                patch.object(retention, "disk_space", return_value={"sufficient": True}),
                patch.object(docker, "remove_image", side_effect=remove_while_locked),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    retention.main(["--policy", "/synthetic-policy.json", "--apply", "--writers-coordinated"]), 0,
                )
            self.assertEqual(docker.removed, [image_id(3)])
            with retention.deployment_lock(lock_path) as descriptor:
                retention.verify_lock(descriptor, lock_path)


if __name__ == "__main__":
    unittest.main()
