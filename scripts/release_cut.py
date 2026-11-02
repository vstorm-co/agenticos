#!/usr/bin/env python3
"""Prepare one cut PR for the changes already merged to main.

Defaults to a plan. --create-pr makes a dedicated worktree, commits the four
release files and opens a PR using the maintainer's gh login, so CI is triggered.
It never merges, tags or publishes. Choose the largest bump in a release train.
"""

import argparse
import json
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

FILES = (
    "CHANGELOG.md",
    "backend/pyproject.toml",
    "backend/uv.lock",
    "frontend/package.json",
)


def cut_files(files: dict[str, str], bump: str, date: str) -> tuple[str, dict[str, str]]:
    manifest: object = json.loads(files["frontend/package.json"])
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise TypeError("Missing frontend version")
    old = manifest["version"]
    match = re.fullmatch(r"1\.(\d+)\.(\d+)", old)
    if match is None or bump not in {"patch", "minor"}:
        raise ValueError("A cut requires major 1 and a patch or minor bump")
    minor, patch = map(int, match.groups())
    new = f"1.{minor + 1}.0" if bump == "minor" else f"1.{minor}.{patch + 1}"
    result = dict(files)
    for path, prefix, suffix in (
        ("backend/pyproject.toml", '[project]\nname = "agenticos"\nversion = "', '"'),
        (
            "backend/uv.lock",
            '[[package]]\nname = "agenticos"\nversion = "',
            '"\nsource = { editable = "." }',
        ),
        ("frontend/package.json", '  "version": "', '",'),
    ):
        needle = f"{prefix}{old}{suffix}"
        if result[path].count(needle) != 1:
            raise ValueError(f"Mismatched application version in {path}")
        result[path] = result[path].replace(needle, f"{prefix}{new}{suffix}")
    changelog = result["CHANGELOG.md"]
    section = re.search(r"(?ms)^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", changelog)
    if section is None or not re.search(r"(?m)^- \S", section[1]):
        raise ValueError("There are no Unreleased entries to cut")
    if f"## [{new}]" in changelog:
        raise ValueError("Release already exists")
    result["CHANGELOG.md"] = changelog.replace(
        "## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {date}", 1
    )
    # Keep reference-style changelog links correct when present.
    result["CHANGELOG.md"] = re.sub(
        r"(?m)^(\[Unreleased\]: .*/compare/)v[^.\n]+(?:\.[^.\n]+){2}\.\.\.HEAD$",
        rf"\g<1>v{new}...HEAD\n[{new}]: https://github.com/vstorm-co/agenticos/compare/v{old}...v{new}",
        result["CHANGELOG.md"],
    )
    return new, result


def run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, text=True, cwd=cwd, timeout=120).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bump", choices=("patch", "minor"))
    parser.add_argument("--create-pr", action="store_true")
    args = parser.parse_args()
    run("git", "fetch", "origin", "main")
    base = run("git", "rev-parse", "origin/main^{commit}")
    files = {path: run("git", "show", f"{base}:{path}") + "\n" for path in FILES}
    version, updated = cut_files(files, args.bump, datetime.now(UTC).date().isoformat())
    branch = f"codex/cut-{version}"
    print(f"Cut {version} from origin/main ({base[:12]}) on {branch}; changes: {', '.join(FILES)}")
    if not args.create_pr:
        print("Plan only. Add --create-pr to prepare and push the cut PR.")
        return
    existing: object = json.loads(run("gh", "pr", "list", "--state", "open", "--json", "title"))
    if not isinstance(existing, list) or any(
        isinstance(pr, dict)
        and isinstance(pr.get("title"), str)
        and pr["title"].startswith("chore: cut ")
        for pr in existing
    ):
        raise ValueError("An open cut PR already exists; finish or close it before another cut")
    # Leave failures available for inspection; remove only after the PR exists.
    worktree = Path(tempfile.mkdtemp(prefix="agenticos-cut-")) / "repo"
    run("git", "worktree", "add", "-b", branch, str(worktree), base)
    for path, content in updated.items():
        (worktree / path).write_text(content)
    run("git", "add", "--", *FILES, cwd=worktree)
    run("git", "diff", "--cached", "--check", cwd=worktree)
    # Release metadata triggers Python guard scripts, but no frontend hooks.
    # Install only locked development tools rather than application dependencies.
    run("uv", "sync", "--locked", "--only-group", "dev", cwd=worktree / "backend")
    run("git", "commit", "-m", f"chore: cut {version}", cwd=worktree)
    run("git", "push", "-u", "origin", branch, cwd=worktree)
    body = worktree.parent / "body.md"
    body.write_text(
        f"Cut {version} from the changes already merged to main. Rename the Unreleased section "
        "and synchronize the application versions; dependencies and application source are unchanged.\n\n"
        "After this PR merges, create the GitHub release and its tag together, targeting its merge commit.\n"
    )
    print(
        run(
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            f"chore: cut {version}",
            "--body-file",
            str(body),
            cwd=worktree,
        )
    )
    run("git", "worktree", "remove", str(worktree))
    body.unlink()
    worktree.parent.rmdir()


if __name__ == "__main__":
    main()
