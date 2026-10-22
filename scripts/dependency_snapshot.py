#!/usr/bin/env python3
"""The backend's locked packages as a GitHub dependency-graph snapshot.

Dependabot builds the dependency graph for `backend/uv.lock` itself, and it
cannot read a project that requires Python 3.15: its job stops at "Dependabot
detected the following Python requirement for your project: '>=3.15'". The
graph then keeps the versions from before that, so every alert on them stays
open after the fix lands - fourteen of them were open on 21 October 2026 against
a lockfile that already held Pillow 13.0.0, certifi 2026.10.19 and virtualenv
21.14.12, the versions the advisories name as fixed.

So the graph is submitted instead, through GitHub's dependency submission API,
from `.github/workflows/dependency-graph.yml` on every push to `main` that moves
the lock. This writes the request body; the workflow posts it:

    python3 scripts/dependency_snapshot.py backend/uv.lock > snapshot.json

Every locked distribution is listed with its exact version as a `pkg:pypi` URL.
A package the project names itself is `direct`, everything else `indirect`; one
reachable only from a dependency group (`dev`, `docs`) is `development`, so an
alert can tell a test tool from something the deployment runs. The project's
own editable package is not a dependency and is left out.

The job's identity comes from the environment GitHub Actions sets -
`GITHUB_SHA`, `GITHUB_REF`, `GITHUB_RUN_ID` and `GITHUB_REPOSITORY` - and is
required: a snapshot with no commit to attach to is refused by the API anyway.
"""

import json
import os
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

CORRELATOR = "uv-lock-backend"
"""One snapshot series: each new one replaces the last for this manifest."""

Scope = Literal["runtime", "development"]


def package_url(name: str, version: str) -> str:
    """The purl for a PyPI distribution: lower case, runs of `-_.` as one `-`."""
    return f"pkg:pypi/{re.sub(r'[-_.]+', '-', name).lower()}@{version}"


def _references(
    entries: Iterable[Mapping[str, Any]], versions: Mapping[str, list[str]]
) -> set[str]:
    """`name@version` keys for the lock's dependency entries.

    An entry pins its version only when the lock holds the name at more than
    one version; without one it is every version locked under that name.
    """
    keys: set[str] = set()
    for entry in entries:
        name = entry["name"]
        pinned = entry.get("version")
        for version in [pinned] if pinned else versions.get(name, []):
            keys.add(f"{name}@{version}")
    return keys


def _reachable(start: set[str], edges: Mapping[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        key = todo.pop()
        if key in seen:
            continue
        seen.add(key)
        todo.extend(edges.get(key, ()))
    return seen


def resolved(lock: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every locked distribution, keyed `name@version`, in the API's shape."""
    packages = lock["package"]
    roots = [package for package in packages if "editable" in package.get("source", {})]
    locked = [package for package in packages if package not in roots]
    versions: dict[str, list[str]] = {}
    for package in locked:
        versions.setdefault(package["name"], []).append(package["version"])

    edges = {
        f"{package['name']}@{package['version']}": _references(
            package.get("dependencies", []), versions
        )
        for package in locked
    }
    runtime_direct: set[str] = set()
    development_direct: set[str] = set()
    for root in roots:
        runtime_direct |= _references(root.get("dependencies", []), versions)
        for entries in root.get("optional-dependencies", {}).values():
            runtime_direct |= _references(entries, versions)
        for entries in root.get("dev-dependencies", {}).values():
            development_direct |= _references(entries, versions)
    runtime = _reachable(runtime_direct, edges)

    entries: dict[str, dict[str, Any]] = {}
    for package in locked:
        key = f"{package['name']}@{package['version']}"
        scope: Scope = "runtime" if key in runtime else "development"
        entries[key] = {
            "package_url": package_url(package["name"], package["version"]),
            "relationship": (
                "direct" if key in runtime_direct | development_direct else "indirect"
            ),
            "scope": scope,
            "dependencies": sorted(
                package_url(*dependency.split("@", 1)) for dependency in edges[key]
            ),
        }
    return entries


def snapshot(lock_path: Path, env: Mapping[str, str], *, now: datetime) -> dict[str, Any]:
    """The request body for `POST /repos/{owner}/{repo}/dependency-graph/snapshots`.

    Raises:
        KeyError: A variable GitHub Actions sets is missing.
    """
    lock = tomllib.loads(lock_path.read_text())
    manifest = lock_path.as_posix()
    return {
        "version": 0,
        "sha": env["GITHUB_SHA"],
        "ref": env["GITHUB_REF"],
        "job": {"correlator": CORRELATOR, "id": env["GITHUB_RUN_ID"]},
        "detector": {
            "name": "agenticos-uv-lock",
            "version": "1",
            "url": f"https://github.com/{env['GITHUB_REPOSITORY']}/blob/main/scripts/dependency_snapshot.py",
        },
        "scanned": now.isoformat(timespec="seconds"),
        "manifests": {
            manifest: {
                "name": manifest,
                "file": {"source_location": manifest},
                "resolved": resolved(lock),
            }
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: dependency_snapshot.py <path to uv.lock>", file=sys.stderr)
        return 2
    try:
        body = snapshot(Path(argv[1]), os.environ, now=datetime.now(UTC))
    except KeyError as missing:
        print(f"{missing.args[0]} is not set; run this inside GitHub Actions", file=sys.stderr)
        return 2
    json.dump(body, sys.stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
