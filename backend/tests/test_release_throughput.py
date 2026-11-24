"""Exercise release reuse with real git trees, including unsafe near misses."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
import yaml

GIT = shutil.which("git")
assert GIT is not None

ROOT = Path(__file__).resolve().parents[2]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scope = load("ci_release_scope")
cut = load("release_cut")
browser = load("browser_image_key")


def git(*args: str) -> str:
    return subprocess.check_output([GIT, *args], text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.chdir(tmp_path)
    git("init", "-q", "--initial-branch=fixture-source")
    git("config", "user.name", "Release test")
    git("config", "user.email", "test@example.com")
    files = {
        "CHANGELOG.md": "## [Unreleased]\n\n### Fixed\n\n- A fix.\n\n## [1.0.0] - 2026-01-01\n",
        "backend/pyproject.toml": '[project]\nname = "agenticos"\nversion = "1.0.0"\n',
        "backend/uv.lock": '[[package]]\nname = "agenticos"\nversion = "1.0.0"\nsource = { editable = "." }\n',
        "frontend/package.json": '{\n  "version": "1.0.0",\n  "private": true\n}\n',
        "source.py": "print('checked')\n",
    }
    for path, content in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git("add", ".")
    git("commit", "-qm", "source")
    base = git("rev-parse", "HEAD")
    _, updated = cut.cut_files({path: files[path] for path in cut.FILES}, "patch", "2026-11-02")
    for path, content in updated.items():
        (tmp_path / path).write_text(content)
    git("add", ".")
    git("commit", "-qm", "cut")
    return base, git("rev-parse", "HEAD")


def test_cut_and_equivalent_checked_source(repository: tuple[str, str]) -> None:
    base, head = repository
    assert scope.is_cut(base, head)
    assert scope.equivalent(base, head)
    assert not scope.is_cut(head, head)
    assert not scope.is_cut(head, base)


@pytest.mark.parametrize("attack", ["dependency", "source", "mode", "versions", "symlink"])
def test_near_miss_requires_full_checks(repository: tuple[str, str], attack: str) -> None:
    base, _ = repository
    if attack == "dependency":
        with Path("backend/uv.lock").open("a") as handle:
            handle.write('\n[[package]]\nname = "dependency"\nversion = "3.2.1"\n')
    elif attack == "source":
        Path("source.py").write_text("print('unchecked')\n")
    elif attack == "mode":
        Path("frontend/package.json").chmod(0o755)
    elif attack == "versions":
        path = Path("frontend/package.json")
        path.write_text(path.read_text().replace("1.0.1", "1.0.2"))
    else:
        path = Path("frontend/package.json")
        path.unlink()
        path.symlink_to("../source.py")
    git("add", ".")
    git("commit", "-qm", "unsafe")
    try:
        assert not scope.is_cut(base, "HEAD")
    except ValueError:
        # Invalid metadata is handled by main as a visible full-run decision.
        assert attack == "versions"


@pytest.mark.parametrize("missing", [None, "test", "test-frontend", "e2e"])
def test_evidence_requires_real_successful_suites(
    repository: tuple[str, str], monkeypatch: pytest.MonkeyPatch, missing: str | None
) -> None:
    base, head = repository

    def api(endpoint: str) -> object:
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"head_sha": base, "id": 42, "event": "push"}]}
        return {
            "jobs": [
                {"name": name, "conclusion": "skipped" if name == missing else "success"}
                for name in ("test", "test-frontend", "e2e")
            ]
        }

    monkeypatch.setattr(scope, "api", api)
    assert scope.checked_source("owner/repo", "ci.yml", head) == (42 if missing is None else None)


def test_api_failure_falls_back_to_full_run(
    repository: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base, head = repository
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": base}))
    for name, value in {
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SHA": head,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REPOSITORY": "owner/repo",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["scope", "--workflow", "ci.yml"])

    def fail(_: str) -> object:
        raise subprocess.TimeoutExpired("gh", 30)

    monkeypatch.setattr(scope, "api", fail)
    scope.main()
    output = capsys.readouterr()
    assert "cut=true" in output.out
    assert "reuse=false" in output.out
    assert "Full checks required" in output.err


def test_cut_tool_rejects_empty_train(repository: tuple[str, str]) -> None:
    files = {path: Path(path).read_text() for path in cut.FILES}
    with pytest.raises(ValueError, match="no Unreleased entries"):
        cut.cut_files(files, "minor", "2026-11-02")


def test_browser_key_invalidates_all_build_inputs() -> None:
    first = browser.cache_key("a" * 40, "sha256:" + "b" * 64, "2026-W45")
    assert first != browser.cache_key("c" * 40, "sha256:" + "b" * 64, "2026-W45")
    assert first != browser.cache_key("a" * 40, "sha256:" + "c" * 64, "2026-W45")
    assert first != browser.cache_key("a" * 40, "sha256:" + "b" * 64, "2026-W46")
    with pytest.raises(ValueError):
        browser.cache_key("a" * 40, "latest", "2026-W45")


def test_retagging_still_scans_and_generates_every_sbom() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows-disabled/images.yml").read_text())
    for name in ("scan", "sbom"):
        condition = workflow["jobs"][name]["if"]
        assert "!cancelled()" in condition
        assert "needs.publish.result == 'success'" in condition
        assert "needs.resolve.result == 'success'" in condition


def test_production_automatic_deploys_follow_stable_releases() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows-disabled/deploy.yml").read_text())
    assert "push" not in workflow[True]
    assert workflow[True]["release"] == {"types": ["published"]}
    assert "workflow_dispatch" in workflow[True]
    resolve = workflow["jobs"]["resolve"]
    assert "!github.event.release.prerelease" in resolve["if"]
    assert "!github.event.release.draft" in resolve["if"]
    pin = next(step for step in resolve["steps"] if step.get("id") == "pin")
    assert "github.event.release.tag_name" in pin["env"]["REF"]
    assert "git merge-base --is-ancestor" in pin["run"]
    assert workflow["jobs"]["deploy"]["environment"]["name"] == "production"


@pytest.mark.parametrize(
    ("mode", "expected", "cached"),
    [
        ("all", [], False),
        ("missing", ["backend", "frontend", "browser"], False),
        ("cached", ["backend", "frontend"], True),
        ("partial", ["frontend", "browser"], False),
    ],
)
def test_image_resolver_builds_only_missing_images(
    repository: tuple[str, str], tmp_path: Path, mode: str, expected: list[str], cached: bool
) -> None:
    import os

    context = tmp_path / "docker/browser"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text(
        "ARG BROWSER_BASE=debian:bookworm-slim\nFROM ${BROWSER_BASE}\n"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "browser_image_key.py").write_text(
        (ROOT / "scripts/browser_image_key.py").read_text()
    )
    git("add", ".")
    git("commit", "-qm", "browser inputs")
    sha = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", sha)
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text("""#!/bin/sh
case "$*" in
  *debian:bookworm-slim*) printf '{"digest":"sha256:%064d"}\\n' 1 ;;
  *:input-*)
    if [ "$MODE" = cached ]; then printf '{"digest":"sha256:%064d"}\\n' 2; else exit 1; fi ;;
  *backend:sha-*) [ "$MODE" = all ] || [ "$MODE" = partial ] ;;
  *:sha-*) [ "$MODE" = all ] ;;
  *) exit 2 ;;
esac
""")
    docker.chmod(0o755)
    output = tmp_path / "output"
    workflow = yaml.safe_load((ROOT / ".github/workflows-disabled/images.yml").read_text())
    pin = next(step for step in workflow["jobs"]["resolve"]["steps"] if step.get("id") == "pin")
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, "-c", pin["run"]],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{binary}:{os.environ['PATH']}",
            "MODE": mode,
            "REF": sha,
            "BACKFILL": "",
            "GITHUB_REF": "refs/heads/main",
            "IMAGE_PREFIX": "ghcr.io/owner/app",
            "GITHUB_OUTPUT": str(output),
        },
    )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert json.loads(values["build_images"]) == expected
    assert values["build"] == ("true" if expected else "false")
    assert bool(values["browser_source"]) is cached
    if cached:
        assert values["browser_source"] == "ghcr.io/owner/app-browser@sha256:" + "0" * 63 + "2"


def test_codeql_reuse_needs_all_languages(
    repository: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, head = repository

    def api(endpoint: str) -> object:
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"head_sha": base, "id": 42, "event": "push"}]}
        return {
            "jobs": [
                {"name": f"analyze {language}", "conclusion": "success"}
                for language in ("actions", "javascript-typescript", "python")
            ]
        }

    monkeypatch.setattr(scope, "api", api)
    assert not scope.checked_source("owner/repo", "codeql.yml", head)


def test_cut_cli_uses_fresh_main_and_leaves_the_checkout_untouched(
    repository: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import os

    base, original = repository
    git("branch", "main", base)
    remote = tmp_path.parent / "remote.git"
    git("clone", "--bare", ".", str(remote))
    git("remote", "add", "origin", str(remote))
    binary = tmp_path / "bin"
    binary.mkdir()
    gh = binary / "gh"
    gh.write_text("""#!/bin/sh
case "$*" in
  'pr list '*) echo '[]' ;;
  'pr create '*) echo 'https://example.com/cut-pr' ;;
  *) exit 9 ;;
esac
""")
    uv = binary / "uv"
    uv.write_text("""#!/bin/sh
[ "$*" = 'sync --locked --only-group dev' ] || exit 9
""")
    gh.chmod(0o755)
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}:{os.environ['PATH']}")
    monkeypatch.setattr("sys.argv", ["release-cut", "minor", "--create-pr"])
    original_run = cut.run
    moved = False

    def concurrent_fetch(*args: str, cwd: Path | None = None) -> str:
        nonlocal moved
        result = original_run(*args, cwd=cwd)
        if args[:2] == ("git", "show") and not moved:
            # Another worktree can fetch while release preparation reads files.
            git("update-ref", "refs/remotes/origin/main", original)
            moved = True
        return result

    monkeypatch.setattr(cut, "run", concurrent_fetch)
    cut.main()
    assert "https://example.com/cut-pr" in capsys.readouterr().out
    assert git("rev-parse", "HEAD") == original
    new = git("rev-parse", "origin/codex/cut-1.1.0")
    assert git("rev-parse", f"{new}^") == base
    assert set(git("diff", "--name-only", base, new).splitlines()) == set(cut.FILES)
    assert scope.is_cut(base, new)
    assert git("tag", "--list") == ""


def test_pr_evidence_checks_the_actual_merge_tree(
    repository: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, head = repository
    Path("source.py").write_text("print('different base merged during checks')\n")
    git("add", ".")
    git("commit", "-qm", "synthetic merge")
    merged = git("rev-parse", "HEAD")

    def api(endpoint: str) -> object:
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"head_sha": base, "id": 42, "event": "pull_request"}]}
        return {
            "jobs": [
                {"name": name, "conclusion": "success"} for name in ("test", "test-frontend", "e2e")
            ]
        }

    monkeypatch.setattr(scope, "api", api)
    monkeypatch.setattr(scope, "checked_commit", lambda *_: merged)
    assert not scope.checked_source("owner/repo", "ci.yml", head)
    monkeypatch.setattr(scope, "checked_commit", lambda *_: base)
    assert scope.checked_source("owner/repo", "ci.yml", head)


def test_pr_without_checkout_evidence_cannot_be_reused(
    repository: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, head = repository

    def api(endpoint: str) -> object:
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"head_sha": base, "id": 42, "event": "pull_request"}]}
        return {
            "jobs": [
                {"name": name, "conclusion": "success"} for name in ("test", "test-frontend", "e2e")
            ]
        }

    def missing(*_: object) -> str:
        raise subprocess.CalledProcessError(1, "gh run download")

    monkeypatch.setattr(scope, "api", api)
    monkeypatch.setattr(scope, "checked_commit", missing)
    assert not scope.checked_source("owner/repo", "ci.yml", head)


@pytest.mark.parametrize("missing", [None, "rust"])
def test_codeql_requires_all_original_sarif_artifacts(
    repository: tuple[str, str], monkeypatch: pytest.MonkeyPatch, missing: str | None
) -> None:
    base, head = repository
    languages = ("actions", "javascript-typescript", "python", "rust")

    def api(endpoint: str) -> object:
        if "/runs?" in endpoint:
            return {"workflow_runs": [{"head_sha": base, "id": 42, "event": "push"}]}
        if "/artifacts?" in endpoint:
            return {
                "artifacts": [
                    {"name": f"codeql-sarif-{language}", "expired": False}
                    for language in languages
                    if language != missing
                ]
            }
        return {
            "jobs": [
                {"name": f"analyze {language}", "conclusion": "success"} for language in languages
            ]
        }

    monkeypatch.setattr(scope, "api", api)
    assert scope.checked_source("owner/repo", "codeql.yml", head) == (
        42 if missing is None else None
    )
