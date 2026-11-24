"""Focused regression coverage for the downstream sync trust boundary."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import ci.downstream_sync as sync
from ci.downstream_sync import (
    Git,
    Refused,
    enable_auto_merge,
    load_config,
    managed_description,
    prepare_commit,
    read_metadata,
    read_state,
    sync_target,
    verified_source,
)


class DownstreamSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.git = Git(self.directory, allow_local=True)
        self.git.run("init", "-q")
        self.git.run("config", "user.name", "Test")
        self.git.run("config", "user.email", "test@example.invalid")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, message: str) -> str:
        self.git.run("add", "-A")
        self.git.run("commit", "-qm", message)
        return self.git.text("rev-parse", "HEAD")

    def lock_history(self) -> tuple[dict, dict, str, str, str]:
        """Create a pinned source history with a private downstream commit."""
        source = {"repository": "t3grp/agenticos", "branch": "t3"}
        target = {"repository": "example-org/client-overlay", "mode": "lock"}
        (self.directory / "upstream.lock.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repository": "https://github.com/t3grp/agenticos.git",
                    "branch": "t3",
                    "commit": "0" * 40,
                    "private_note": "keep me",
                }
            )
            + "\n"
        )
        (self.directory / "overlay.txt").write_text("private scheduler config\n")
        previous = self.commit("source v1")
        lock = json.loads((self.directory / "upstream.lock.json").read_text())
        lock["commit"] = previous
        (self.directory / "upstream.lock.json").write_text(json.dumps(lock) + "\n")
        self.commit("pin source v1")
        (self.directory / "private.txt").write_text("human changes\n")
        base = self.commit("private downstream change")
        self.git.run("branch", "downstream-base", base)
        self.git.run("checkout", "-q", "-b", "source-line", previous)
        (self.directory / "source.txt").write_text("source v2\n")
        latest = self.commit("source v2")
        self.git.run("checkout", "-q", "downstream-base")
        return source, target, previous, base, latest

    @staticmethod
    def source_config() -> dict:
        return {
            "source": {"repository": "t3grp/agenticos", "branch": "t3"},
            "validation": {
                "project": "trusted-project",
                "region": "us-central1",
                "trigger_id": "trigger-123",
                "service_account": "projects/trusted-project/serviceAccounts/ci@example.invalid",
                "repository_resource": "projects/trusted-project/locations/us-central1/connections/github/repositories/agenticos",
                "required_steps": ["lint", "tests"],
            },
        }

    def valid_build(self, sha: str) -> dict:
        return {
            "id": "build-abc",
            "projectId": "trusted-project",
            "buildTriggerId": "trigger-123",
            "serviceAccount": "projects/trusted-project/serviceAccounts/ci@example.invalid",
            "status": "SUCCESS",
            "sourceProvenance": {
                "resolvedConnectedRepository": {
                    "repository": "projects/trusted-project/locations/us-central1/connections/github/repositories/agenticos",
                    "revision": sha,
                }
            },
            "substitutions": {"BRANCH_NAME": "t3", "_SOURCE_SHA": sha},
            "steps": [
                {"id": "lint", "status": "SUCCESS"},
                {"id": "tests", "status": "SUCCESS"},
            ],
        }

    def test_build_evidence_requires_exact_trusted_identity_and_steps(self) -> None:
        sha = "a" * 40
        config = self.source_config()
        self.assertEqual(
            verified_source(self.valid_build(sha), config, "build-abc"), sha
        )
        cases = [
            ("wrong build id", lambda b: b.update(id="other")),
            ("wrong project", lambda b: b.update(projectId="attacker-project")),
            ("wrong trigger", lambda b: b.update(buildTriggerId="other-trigger")),
            ("wrong service account", lambda b: b.update(serviceAccount="untrusted")),
            ("unsuccessful build", lambda b: b.update(status="CANCELLED")),
            (
                "other repository",
                lambda b: b["sourceProvenance"]["resolvedConnectedRepository"].update(
                    repository="projects/trusted-project/locations/us-central1/connections/evil/repositories/fork"
                ),
            ),
            (
                "branch mismatch",
                lambda b: b["substitutions"].update(BRANCH_NAME="attacker"),
            ),
            (
                "sha substitution mismatch",
                lambda b: b["substitutions"].update(_SOURCE_SHA="b" * 40),
            ),
            ("failed step", lambda b: b["steps"][1].update(status="FAILURE")),
            ("allowed failure", lambda b: b["steps"][1].update(allowFailure=True)),
            ("allowed exit code", lambda b: b["steps"][1].update(allowExitCodes=[1])),
        ]
        for label, mutate in cases:
            with self.subTest(label=label):
                build = self.valid_build(sha)
                mutate(build)
                with self.assertRaises(Refused):
                    verified_source(build, config, "build-abc")

    def test_sync_commit_preserves_private_work_and_source_ancestry(self) -> None:
        source = {"repository": "t3grp/agenticos", "branch": "t3"}
        target = {"repository": "example-org/client-fork", "mode": "merge"}
        metadata = {
            "schema_version": 1,
            "parent": {
                "repository": "https://github.com/t3grp/agenticos.git",
                "branch": "t3",
                "commit": "0" * 40,
            },
            "private": {"owner": "Betty"},
        }
        # Build a shared history as a real fork would: upstream commit, downstream
        # private commit, then the next upstream commit.
        (self.directory / "integrations").mkdir()
        metadata["parent"]["commit"] = "1" * 40  # replaced with actual commit below
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(metadata) + "\n"
        )
        (self.directory / "platform.txt").write_text("upstream v1\n")
        upstream_one = self.commit("upstream one")
        metadata["parent"]["commit"] = upstream_one
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(metadata) + "\n"
        )
        self.commit("pin upstream one")
        (self.directory / "private.txt").write_text("Betty's work\n")
        downstream_base = self.commit("private downstream work")
        self.git.run("branch", "downstream-base", downstream_base)
        self.git.run("checkout", "-q", "-b", "source-line", upstream_one)
        (self.directory / "platform.txt").write_text("upstream v2\n")
        source_two = self.commit("upstream two")
        self.git.run("checkout", "-q", "downstream-base")
        result = prepare_commit(
            self.git, target, source, source_two, downstream_base, "test-secret"
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            self.git.text("show", "-s", "--format=%P", result).split(),
            [downstream_base, source_two],
        )
        self.assertTrue(self.git.ancestor(upstream_one, result))
        self.assertEqual((self.directory / "private.txt").read_text(), "Betty's work\n")
        updated = json.loads(
            (self.directory / "integrations/downstream.json").read_text()
        )
        self.assertEqual(updated["parent"]["commit"], source_two)
        self.assertEqual(updated["private"], {"owner": "Betty"})
        state = read_state(self.git, result, "test-secret", "example-org/client-fork")
        self.assertEqual(state["source_sha"], source_two)

    def test_merge_conflict_aborts_without_creating_update_commit(self) -> None:
        source = {"repository": "t3grp/agenticos", "branch": "t3"}
        target = {"repository": "example-org/client-fork", "mode": "merge"}
        (self.directory / "integrations").mkdir()
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "parent": {
                        "repository": "https://github.com/t3grp/agenticos.git",
                        "branch": "t3",
                        "commit": "0" * 40,
                    },
                }
            )
            + "\n"
        )
        (self.directory / "platform.txt").write_text("one\n")
        first = self.commit("first")
        metadata = json.loads(
            (self.directory / "integrations/downstream.json").read_text()
        )
        metadata["parent"]["commit"] = first
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(metadata) + "\n"
        )
        pinned = self.commit("pin first")
        (self.directory / "platform.txt").write_text("downstream edit\n")
        base = self.commit("downstream edit")
        self.git.run("branch", "downstream-base", base)
        self.git.run("checkout", "-q", "-b", "source-line", pinned)
        (self.directory / "platform.txt").write_text("upstream edit\n")
        source_tip = self.commit("upstream edit")
        self.git.run("checkout", "-q", "downstream-base")
        with self.assertRaises(Refused):
            prepare_commit(self.git, target, source, source_tip, base, "secret")
        self.assertEqual(self.git.text("rev-parse", "HEAD"), base)

    def test_signed_state_rejects_commit_message_tampering(self) -> None:
        source = {"repository": "t3grp/agenticos", "branch": "t3"}
        target = {"repository": "example-org/client-fork", "mode": "lock"}
        (self.directory / "upstream.lock.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repository": "https://github.com/t3grp/agenticos.git",
                    "branch": "t3",
                    "commit": "0" * 40,
                }
            )
            + "\n"
        )
        previous = self.commit("old lock")
        metadata = json.loads((self.directory / "upstream.lock.json").read_text())
        metadata["commit"] = previous
        (self.directory / "upstream.lock.json").write_text(json.dumps(metadata) + "\n")
        base = self.commit("pin old lock")
        (self.directory / "new-upstream-file").write_text("new source\n")
        source_tip = self.commit("new source")
        signed = prepare_commit(self.git, target, source, source_tip, base, "secret")
        self.assertIsNotNone(signed)
        assert signed is not None
        tree = self.git.text("rev-parse", f"{signed}^{{tree}}")
        parents = self.git.text("show", "-s", "--format=%P", signed).split()
        args = ["commit-tree", tree]
        for parent in parents:
            args.extend(["-p", parent])
        replacement = self.git.text(*args, "-m", "tampered")
        with self.assertRaises(Refused):
            read_state(self.git, replacement, "secret", "example-org/client-fork")

    def test_lock_mode_updates_only_upstream_pin_and_preserves_private_data(
        self,
    ) -> None:
        source, target, _previous, base, latest = self.lock_history()
        result = prepare_commit(self.git, target, source, latest, base, "secret")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(self.git.ancestor(base, result))
        metadata = json.loads((self.directory / "upstream.lock.json").read_text())
        self.assertEqual(metadata["commit"], latest)
        self.assertEqual(metadata["private_note"], "keep me")
        self.assertEqual(
            (self.directory / "overlay.txt").read_text(), "private scheduler config\n"
        )
        self.assertEqual(
            (self.directory / "private.txt").read_text(), "human changes\n"
        )
        self.assertEqual(
            self.git.text("diff", "--name-only", base, result), "upstream.lock.json"
        )

    def test_repeated_source_is_noop_and_stale_source_cannot_rollback(self) -> None:
        source, target, previous, base, latest = self.lock_history()
        result = prepare_commit(self.git, target, source, latest, base, "secret")
        assert result is not None
        self.git.run("checkout", "-q", result)
        self.assertIsNone(
            prepare_commit(self.git, target, source, latest, result, "secret")
        )
        self.assertEqual(self.git.text("rev-parse", "HEAD"), result)
        self.assertIsNone(
            prepare_commit(self.git, target, source, previous, result, "secret")
        )
        self.assertEqual(self.git.text("rev-parse", "HEAD"), result)

    def test_same_source_with_advanced_base_keeps_existing_bot_ancestry(self) -> None:
        source, target, _previous, base, latest = self.lock_history()
        first = prepare_commit(self.git, target, source, latest, base, "secret")
        assert first is not None
        self.git.run("checkout", "-q", first)
        (self.directory / "new-private-file.txt").write_text("new human work\n")
        advanced_base = self.commit("advance target base")
        self.git.run("checkout", "-q", first)
        second = prepare_commit(
            self.git, target, source, latest, advanced_base, "secret"
        )
        self.assertIsNotNone(second)
        assert second is not None
        self.assertTrue(self.git.ancestor(first, second))
        self.assertTrue(self.git.ancestor(advanced_base, second))
        self.assertEqual(
            json.loads((self.directory / "upstream.lock.json").read_text())["commit"],
            latest,
        )
        self.assertEqual(
            (self.directory / "new-private-file.txt").read_text(), "new human work\n"
        )

    def test_signed_state_rejects_tree_or_parent_substitution(self) -> None:
        source, target, _previous, base, latest = self.lock_history()
        signed = prepare_commit(self.git, target, source, latest, base, "secret")
        assert signed is not None
        original_tree = self.git.text("rev-parse", f"{signed}^{{tree}}")
        original_parents = self.git.text("show", "-s", "--format=%P", signed).split()
        (self.directory / "substitution.txt").write_text("altered tree\n")
        self.git.run("add", "substitution.txt")
        changed_tree = self.git.text("write-tree")
        self.git.run("reset", "--hard", signed)
        variants = [
            (changed_tree, original_parents),
            (original_tree, [original_parents[0]]),
        ]
        for index, (tree, parents) in enumerate(variants):
            args = ["commit-tree", tree]
            for parent in parents:
                args.extend(["-p", parent])
            changed = self.git.text(*args, "-m", f"substitution {index}")
            with self.subTest(variant=index), self.assertRaises(Refused):
                read_state(self.git, changed, "secret", target["repository"])

    def test_fork_sync_refuses_incoming_workflow_changes(self) -> None:
        source = {"repository": "t3grp/agenticos", "branch": "t3"}
        target = {"repository": "example-org/client-fork", "mode": "merge"}
        (self.directory / "integrations").mkdir()
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "parent": {
                        "repository": "https://github.com/t3grp/agenticos.git",
                        "branch": "t3",
                        "commit": "0" * 40,
                    },
                }
            )
            + "\n"
        )
        (self.directory / "platform.txt").write_text("one\n")
        first = self.commit("first source")
        metadata = json.loads(
            (self.directory / "integrations/downstream.json").read_text()
        )
        metadata["parent"]["commit"] = first
        (self.directory / "integrations/downstream.json").write_text(
            json.dumps(metadata) + "\n"
        )
        base = self.commit("pin source")
        self.git.run("branch", "downstream-base", base)
        self.git.run("checkout", "-q", "-b", "source-line", first)
        (self.directory / ".github/workflows").mkdir(parents=True)
        (self.directory / ".github/workflows/new.yml").write_text("name: unreviewed\n")
        workflow_sha = self.commit("add workflow")
        self.git.run("checkout", "-q", "downstream-base")
        with self.assertRaisesRegex(Refused, "workflow"):
            prepare_commit(self.git, target, source, workflow_sha, base, "secret")
        self.assertEqual(self.git.text("rev-parse", "HEAD"), base)

    def test_metadata_symlink_is_refused(self) -> None:
        source, target, _previous, _base, _latest = self.lock_history()
        real = self.directory / "outside.json"
        metadata_path = self.directory / "upstream.lock.json"
        metadata_path.rename(real)
        metadata_path.symlink_to(real)
        self.git.run("add", "-A")
        self.git.run("commit", "-qm", "replace lock with symlink")
        with self.assertRaisesRegex(Refused, "regular tracked file"):
            read_metadata(self.git, target, source)

    def valid_app_config(self) -> dict:
        return {
            "schema_version": 1,
            **self.source_config(),
            "github_app": {"app_id": 11, "installation_id": 22, "slug": "sync-app"},
            "downstreams": [
                {
                    "repository": "example-org/client-fork",
                    "base_branch": "betty",
                    "mirror_branch": "t3",
                    "mode": "merge",
                    "auto_merge": False,
                }
            ],
        }

    def test_config_rejects_unbound_auto_merge_checks_and_malformed_ids_or_branches(
        self,
    ) -> None:
        config = self.valid_app_config()
        config["downstreams"][0].update(
            auto_merge=True, required_checks=[{"context": "ci", "app_id": 0}]
        )
        with self.assertRaises(Refused):
            load_config(json.dumps(config))
        for mutate in (
            lambda c: c["validation"].update(trigger_id="bad/id"),
            lambda c: c["source"].update(branch="bad branch"),
            lambda c: c["downstreams"][0].update(base_branch="bad branch"),
        ):
            broken = self.valid_app_config()
            mutate(broken)
            with self.subTest(config=broken), self.assertRaises(Refused):
                load_config(json.dumps(broken))

    def test_managed_description_preserves_human_notes_and_requires_markers(
        self,
    ) -> None:
        original = "Human context\n\n<!-- t3os-sync:begin -->old<!-- t3os-sync:end -->\n\nMore notes"
        result = managed_description(original, "new sync details")
        self.assertTrue(result.startswith("Human context\n"))
        self.assertIn("new sync details", result)
        self.assertTrue(result.endswith("\n\nMore notes"))
        with self.assertRaises(Refused):
            managed_description("Human context with deleted marker", "new body")

    def test_auto_merge_requires_matching_protected_producer_and_uses_merge_for_fork(
        self,
    ) -> None:
        class FakeApi:
            def __init__(self, protection: dict) -> None:
                self.protection = protection
                self.calls: list[tuple[str, str, dict | None]] = []

            def call(self, method: str, path: str, data=None):
                self.calls.append((method, path, data))
                if method == "GET":
                    return self.protection
                return {
                    "data": {
                        "enablePullRequestAutoMerge": {"pullRequest": {"number": 7}}
                    }
                }

        target = {
            "base_branch": "betty",
            "mode": "merge",
            "required_checks": [{"context": "CI / required", "app_id": 99}],
        }
        pr = {"node_id": "PR_node", "draft": False}
        cases = [
            {
                "required_status_checks": {
                    "strict": False,
                    "checks": target["required_checks"],
                }
            },
            {
                "required_status_checks": {
                    "strict": True,
                    "checks": [{"context": "CI / required", "app_id": 100}],
                }
            },
            {},
        ]
        for protection in cases:
            api = FakeApi(protection)
            with self.subTest(protection=protection), self.assertRaises(Refused):
                enable_auto_merge(api, "example-org/client-fork", target, pr)
            self.assertEqual(len(api.calls), 1)
        api = FakeApi(
            {
                "required_status_checks": {
                    "strict": True,
                    "checks": target["required_checks"],
                }
            }
        )
        enable_auto_merge(api, "example-org/client-fork", target, pr)
        self.assertEqual(api.calls[1][2]["variables"]["method"], "MERGE")


class SyncTargetIntegrationTests(unittest.TestCase):
    """Exercise sync_target through real local bare remotes and a fake API."""

    repository = "example-org/client-overlay"
    source_repository = "t3grp/agenticos"

    class LocalGit(Git):
        remote_map: ClassVar[dict[str, str]] = {}

        def __init__(self, directory: Path) -> None:
            super().__init__(directory, allow_local=True)

        def run(self, *args, **kwargs):
            mapped = tuple(self.remote_map.get(arg, arg) for arg in args)
            return super().run(*mapped, **kwargs)

    class FakeApi:
        def __init__(self, target_bare: Path) -> None:
            self.token = "target-token"
            self.repository = SyncTargetIntegrationTests.repository
            self.target_bare = target_bare
            self.prs: list[dict] = []
            self.calls: list[tuple[str, str, dict | None]] = []
            self.closed: list[dict] = []

        def head(self, repository: str, branch: str) -> str:
            result = subprocess.run(
                [
                    "git",
                    "--git-dir",
                    str(self.target_bare),
                    "rev-parse",
                    f"refs/heads/{branch}",
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            if result.returncode:
                raise Refused("missing local test ref")
            return result.stdout.strip()

        def pages(self, path: str) -> list[dict]:
            return self.prs if "state=open" in path else self.closed

        def call(self, method: str, path: str, data=None):
            self.calls.append((method, path, data))
            if method == "POST" and path.endswith("/pulls"):
                pr = {
                    "number": len(self.prs) + 1,
                    "node_id": "PR_node",
                    "state": "open",
                    "draft": False,
                    "html_url": "https://github.com/example-org/client-overlay/pull/1",
                    "user": {"login": "sync-app[bot]"},
                    "head": {
                        "ref": "sync/t3-updates",
                        "sha": self.head(self.repository, "sync/t3-updates"),
                        "repo": {"full_name": self.repository},
                    },
                    "base": {"ref": "main"},
                    "body": data["body"],
                }
                self.prs.append(pr)
                return pr
            if method == "GET" and "/pulls/" in path:
                return self.prs[0]
            if method == "PATCH" and "/pulls/" in path:
                self.prs[0].update(data)
                return self.prs[0]
            raise AssertionError(f"unexpected API request: {method} {path}")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_bare = self.root / "source.git"
        self.target_bare = self.root / "target.git"
        self.source_work = self.root / "source-work"
        self.target_work = self.root / "target-work"
        for bare in (self.source_bare, self.target_bare):
            subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        self.source_work.mkdir()
        self.target_work.mkdir()
        self.source_git = self.LocalGit(self.source_work)
        self.source_git.run("init", "-q")
        self.source_git.run("config", "user.name", "Fixture")
        self.source_git.run("config", "user.email", "fixture@example.invalid")
        (self.source_work / "upstream.lock.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repository": "https://github.com/t3grp/agenticos.git",
                    "branch": "t3",
                    "commit": "0" * 40,
                }
            )
            + "\n"
        )
        (self.source_work / "platform.txt").write_text("platform v1\n")
        self.source_git.run("add", "-A")
        self.source_git.run("commit", "-qm", "source v1")
        self.previous = self.source_git.text("rev-parse", "HEAD")
        self.source_git.run("remote", "add", "origin", str(self.source_bare))
        self.source_git.run("push", "-q", "origin", "HEAD:refs/heads/t3")
        (self.source_work / "platform.txt").write_text("platform v2\n")
        self.source_git.run("add", "-A")
        self.source_git.run("commit", "-qm", "source v2")
        self.latest = self.source_git.text("rev-parse", "HEAD")
        self.source_git.run("push", "-q", "origin", "HEAD:refs/heads/t3")

        self.target_git = self.LocalGit(self.target_work)
        self.target_git.run("init", "-q")
        self.target_git.run("config", "user.name", "Fixture")
        self.target_git.run("config", "user.email", "fixture@example.invalid")
        self.target_git.run("remote", "add", "source", str(self.source_bare))
        self.target_git.run("fetch", "-q", "source", self.previous)
        self.target_git.run("checkout", "-q", "-b", "main", self.previous)
        lock = json.loads((self.target_work / "upstream.lock.json").read_text())
        lock["commit"] = self.previous
        (self.target_work / "upstream.lock.json").write_text(json.dumps(lock) + "\n")
        (self.target_work / "private-overlay.txt").write_text("private config\n")
        self.target_git.run("add", "-A")
        self.target_git.run("commit", "-qm", "private downstream overlay")
        self.target_git.run("remote", "add", "origin", str(self.target_bare))
        self.target_git.run("push", "-q", "origin", "HEAD:refs/heads/main")
        self.base_sha = self.target_git.text("rev-parse", "HEAD")
        self.api = self.FakeApi(self.target_bare)
        self.source_api = type("SourceApi", (), {"token": "source-token"})()
        self.source = {"repository": self.source_repository, "branch": "t3"}
        self.target = {
            "repository": self.repository,
            "base_branch": "main",
            "mode": "lock",
        }
        self.config = {"source": self.source, "github_app": {"slug": "sync-app"}}
        canonical = sync.canonical_url
        self.LocalGit.remote_map = {
            canonical(self.repository): str(self.target_bare),
            canonical(self.source_repository): str(self.source_bare),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_sync(self, source_sha: str | None = None) -> str:
        source_sha = source_sha or self.latest
        with patch.object(sync, "Git", self.LocalGit):
            return sync_target(
                self.config,
                self.target,
                source_sha,
                "test-signing-key",
                self.source_api,
                self.api,
            )

    def test_duplicate_pr_and_post_push_crash_recovery_are_idempotent(self) -> None:
        self.run_sync()
        self.assertEqual(len(self.api.prs), 1)
        first_head = self.api.head(self.repository, sync.BRANCH)
        # Simulate a run that pushed the signed branch but died before creating the PR.
        self.api.prs.clear()
        self.run_sync()
        self.assertEqual(len(self.api.prs), 1)
        self.assertEqual(self.api.head(self.repository, sync.BRANCH), first_head)
        self.run_sync()
        self.assertEqual(len(self.api.prs), 1)
        self.assertEqual(
            sum(
                method == "POST" and path.endswith("/pulls")
                for method, path, _ in self.api.calls
            ),
            2,
        )

    def test_no_empty_pr_after_prior_squash_or_merge_updated_the_base_pin(self) -> None:
        # Model a previously merged update: target main contains the validated
        # source commit, and its lock points at that commit, with no bot branch.
        self.target_git.run("fetch", "-q", "source", self.latest)
        self.target_git.run("checkout", "-q", "-b", "already-integrated", self.latest)
        lock = json.loads((self.target_work / "upstream.lock.json").read_text())
        lock["commit"] = self.latest
        (self.target_work / "upstream.lock.json").write_text(json.dumps(lock) + "\n")
        self.target_git.run("add", "upstream.lock.json")
        self.target_git.run("commit", "-qm", "record integrated upstream pin")
        integrated = self.target_git.text("rev-parse", "HEAD")
        self.target_git.run(
            "push", "-q", "origin", "HEAD:refs/heads/main", "--force-with-lease"
        )
        self.assertIn("already integrated", self.run_sync())
        self.assertEqual(self.api.prs, [])
        self.assertEqual(self.api.head(self.repository, "main"), integrated)

    def test_git_child_does_not_inherit_unrelated_credentials(self) -> None:
        captured: list[dict[str, str]] = []
        original = subprocess.run

        def recording_run(*args, **kwargs):
            captured.append(kwargs["env"])
            return original(*args, **kwargs)

        git = self.LocalGit(self.root / "credential-check")
        git.directory.mkdir()
        git.run("init", "-q")
        git.auth = {"https://github.com/example/private.git": "only-this-remote-token"}
        with (
            patch.dict(
                os.environ,
                {
                    "GH_TOKEN": "ambient-gh-token",
                    "AWS_SECRET_ACCESS_KEY": "ambient-aws-secret",
                },
            ),
            patch("ci.downstream_sync.subprocess.run", recording_run),
        ):
            git.run("status", "--short")
        self.assertNotIn("GH_TOKEN", captured[0])
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", captured[0])
        self.assertIn("GIT_CONFIG_VALUE_0", captured[0])


if __name__ == "__main__":
    unittest.main()
