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


def checked_source(repository: str, workflow: str, head: str) -> bool:
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
        try:
            command("git", "cat-file", "-e", f"{sha}^{{commit}}")
        except subprocess.CalledProcessError:
            command("git", "fetch", "--no-tags", "--depth=1", "origin", sha)
        if not equivalent(sha, head):
            continue
        jobs = records(api(f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"), "jobs")
        passed = {
            job.get("name")
            for job in jobs
            if job.get("conclusion") == "success" and isinstance(job.get("name"), str)
        }
        if required <= passed:
            print(f"Reusing full {workflow} run {run_id} at {sha}", file=sys.stderr)
            return True
    return False


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
    fast = False
    cut = False
    try:
        base, head = event_commits()
        cut = is_cut(base, head)
        fast = cut and checked_source(os.environ["GITHUB_REPOSITORY"], args.workflow, head)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"Full checks required: {error}", file=sys.stderr)
    print(f"cut={'true' if cut else 'false'}")
    print(f"reuse={'true' if fast else 'false'}")


if __name__ == "__main__":
    main()
