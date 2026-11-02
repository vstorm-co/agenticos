#!/usr/bin/env python3
"""Reuse full checks only for a proven release cut of already checked source.

No evidence, malformed metadata or an API/git failure means a full run. Weekly
CodeQL runs never call this classifier. Evidence must include successful suites,
not just a green workflow whose expensive jobs were skipped.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FILES = (
    "CHANGELOG.md",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/package.json",
)
VERSION = re.compile(r"1\.(\d+)\.(\d+)")


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, timeout=30, stderr=subprocess.PIPE).strip()


def metadata(ref: str) -> tuple[str, tuple[str, ...]]:
    """Normalize only the application version, preserving every other byte."""
    normalized: list[str] = []
    versions: list[str] = []
    for path in FILES[1:]:
        source = command("git", "show", f"{ref}:{path}")
        if path.endswith("package.json"):
            pattern = r'(?m)^(  "version": ")(1\.\d+\.\d+)(",)$'
        elif path.endswith("pyproject.toml"):
            pattern = r'(?m)(\[project\]\nname = "agenticos"\nversion = ")(1\.\d+\.\d+)(")'
        else:
            pattern = r'(\[\[package\]\]\nname = "agenticos"\nversion = ")(1\.\d+\.\d+)("\nsource = \{ editable = "\." \})'
        matches = list(re.finditer(pattern, source))
        if len(matches) != 1:
            raise ValueError(f"Unrecognized application version in {path}")
        versions.append(matches[0][2])
        normalized.append(re.sub(pattern, r"\g<1><VERSION>\g<3>", source))
    if len(set(versions)) != 1:
        raise ValueError("Application versions disagree")
    return versions[0], tuple(normalized)


def equivalent(base: str, head: str) -> bool:
    changed = command("git", "diff", "--name-only", base, head).splitlines()
    if not set(changed) <= set(FILES):
        return False
    # Metadata files must remain regular files with unchanged modes. A symlink
    # to executable source is not a version bump.
    for ref in (base, head):
        tree = command("git", "ls-tree", ref, "--", *FILES).splitlines()
        if len(tree) != len(FILES) or any(not line.startswith("100644 blob ") for line in tree):
            return False
    return metadata(base)[1] == metadata(head)[1]


def is_cut(base: str, head: str) -> bool:
    if set(command("git", "diff", "--name-only", base, head).splitlines()) != set(FILES):
        return False
    if not equivalent(base, head):
        return False
    old, _ = metadata(base)
    new, _ = metadata(head)
    old_match, new_match = VERSION.fullmatch(old), VERSION.fullmatch(new)
    if old_match is None or new_match is None:
        return False
    if tuple(map(int, new_match.groups())) <= tuple(map(int, old_match.groups())):
        return False
    changelog = command("git", "show", f"{head}:CHANGELOG.md")
    return "## [Unreleased]" in changelog and f"## [{new}] - " in changelog


def records(payload: object, key: str) -> list[dict[str, object]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise TypeError(f"Invalid GitHub response: {key}")
    rows = payload[key]
    return [row for row in rows if isinstance(row, dict)]


def api(endpoint: str) -> object:
    return json.loads(command("gh", "api", endpoint))


def checked_commit(repository: str, run: dict[str, object], fallback: str) -> str:
    """PR checkout uses the synthetic merge SHA, not the run API's head SHA."""
    event = run.get("event")
    if event in {"push", "schedule", "workflow_dispatch"}:
        return fallback
    if event != "pull_request":
        raise ValueError("Unrecognized run event")
    run_id = run["id"]
    with tempfile.TemporaryDirectory(prefix="agenticos-checked-source-") as directory:
        command(
            "gh",
            "run",
            "download",
            str(run_id),
            "--repo",
            repository,
            "--name",
            "checked-source",
            "--dir",
            directory,
        )
        sha = (Path(directory) / "checked-source.txt").read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid checked source SHA")
    return sha


def fetch_commit(sha: str) -> None:
    try:
        command("git", "cat-file", "-e", f"{sha}^{{commit}}")
    except subprocess.CalledProcessError:
        command("git", "fetch", "--no-tags", "--depth=1", "origin", sha)


def checked_source(repository: str, workflow: str, head: str) -> int | None:
    runs = records(
        api(f"repos/{repository}/actions/workflows/{workflow}/runs?status=success&per_page=30"),
        "workflow_runs",
    )
    required = (
        {"test", "test-frontend", "e2e"}
        if workflow == "ci.yml"
        else {
            f"analyze {language}"
            for language in ("actions", "javascript-typescript", "python", "rust")
        }
    )
    for run in runs:
        sha, run_id = run.get("head_sha"), run.get("id")
        if (
            not isinstance(sha, str)
            or not re.fullmatch(r"[0-9a-f]{40}", sha)
            or not isinstance(run_id, int)
        ):
            continue
        fetch_commit(sha)
        if not equivalent(sha, head):
            continue
        jobs = records(api(f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"), "jobs")
        passed = {
            job.get("name")
            for job in jobs
            if job.get("conclusion") == "success" and isinstance(job.get("name"), str)
        }
        if required <= passed:
            try:
                checked = checked_commit(repository, run, sha)
                fetch_commit(checked)
                if not equivalent(checked, head):
                    continue
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"Cannot reuse run {run_id}: {error}", file=sys.stderr)
                continue
            if workflow == "codeql.yml":
                artifacts = records(
                    api(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100"),
                    "artifacts",
                )
                available = {
                    artifact.get("name")
                    for artifact in artifacts
                    if artifact.get("expired") is False and isinstance(artifact.get("name"), str)
                }
                expected = {
                    f"codeql-sarif-{language}"
                    for language in ("actions", "javascript-typescript", "python", "rust")
                }
                if not expected <= available:
                    continue
            print(f"Reusing full {workflow} run {run_id} at {checked}", file=sys.stderr)
            return run_id
    return None


def event_commits() -> tuple[str, str]:
    event: object = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if not isinstance(event, dict):
        raise TypeError("Invalid event")
    head = os.environ["GITHUB_SHA"]
    if os.environ["GITHUB_EVENT_NAME"] == "pull_request":
        pr = event.get("pull_request")
        if not isinstance(pr, dict) or not isinstance(pr.get("base"), dict):
            raise ValueError("Invalid pull request")
        base = pr["base"].get("sha")
    else:
        base = event.get("before")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ValueError("Invalid base")
    return base, head


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("ci.yml", "codeql.yml"), required=True)
    args = parser.parse_args()
    evidence: int | None = None
    cut = False
    try:
        base, head = event_commits()
        cut = is_cut(base, head)
        if cut:
            evidence = checked_source(os.environ["GITHUB_REPOSITORY"], args.workflow, head)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"Full checks required: {error}", file=sys.stderr)
    print(f"cut={'true' if cut else 'false'}")
    print(f"reuse={'true' if evidence is not None else 'false'}")
    print(f"evidence_run={evidence if evidence is not None else ''}")


if __name__ == "__main__":
    main()
