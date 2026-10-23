"""What the dependency-graph snapshot says about the locked packages.

Dependabot cannot read a Python 3.15 project, so `scripts/dependency_snapshot.py`
is what GitHub's alerts are matched against: a version it gets wrong is an alert
that never closes, or one that never opens.
"""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "dependency_snapshot_under_test", REPO_ROOT / "scripts" / "dependency_snapshot.py"
)
assert _spec is not None and _spec.loader is not None
dependency_snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dependency_snapshot)

_ENV = {
    "GITHUB_SHA": "f" * 40,
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_RUN_ID": "42",
    "GITHUB_REPOSITORY": "vstorm-co/agenticos",
}

_LOCK = """
version = 1
requires-python = ">=3.15"

[[package]]
name = "agenticos"
version = "1.0.0"
source = { editable = "." }
dependencies = [{ name = "Pillow" }, { name = "httpx" }]

[package.optional-dependencies]
kerberos = [{ name = "gssapi" }]

[package.dev-dependencies]
dev = [{ name = "pytest" }, { name = "httpx" }]

[[package]]
name = "Pillow"
version = "13.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "certifi" }]

[[package]]
name = "certifi"
version = "2026.10.19"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "gssapi"
version = "1.9.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "9.1.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "pluggy" }, { name = "zope.interface", version = "7.0" }]

[[package]]
name = "pluggy"
version = "1.6.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "zope.interface"
version = "7.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "zope.interface"
version = "6.4"
source = { registry = "https://pypi.org/simple" }
"""


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    path = tmp_path / "uv.lock"
    path.write_text(_LOCK)
    return path


def _resolved(lock: Path) -> dict[str, dict[str, object]]:
    body = dependency_snapshot.snapshot(lock, _ENV, now=datetime(2026, 10, 21, tzinfo=UTC))
    return body["manifests"][lock.as_posix()]["resolved"]


def test_every_locked_version_is_listed_and_the_project_is_not(lock: Path) -> None:
    assert set(_resolved(lock)) == {
        "Pillow@13.0.0",
        "httpx@0.28.1",
        "certifi@2026.10.19",
        "gssapi@1.9.0",
        "pytest@9.1.1",
        "pluggy@1.6.0",
        "zope.interface@7.0",
        "zope.interface@6.4",
    }


def test_a_package_url_is_the_normalised_name_at_the_locked_version(lock: Path) -> None:
    resolved = _resolved(lock)
    assert resolved["Pillow@13.0.0"]["package_url"] == "pkg:pypi/pillow@13.0.0"
    assert resolved["zope.interface@7.0"]["package_url"] == "pkg:pypi/zope-interface@7.0"


@pytest.mark.parametrize(
    ("key", "relationship", "scope"),
    [
        ("Pillow@13.0.0", "direct", "runtime"),
        ("gssapi@1.9.0", "direct", "runtime"),
        ("certifi@2026.10.19", "indirect", "runtime"),
        ("httpx@0.28.1", "direct", "runtime"),
        ("pytest@9.1.1", "direct", "development"),
        ("pluggy@1.6.0", "indirect", "development"),
    ],
)
def test_who_names_a_package_decides_its_relationship_and_scope(
    lock: Path, key: str, relationship: str, scope: str
) -> None:
    """`httpx` is in both the runtime list and a group: the deployment runs it."""
    entry = _resolved(lock)[key]
    assert (entry["relationship"], entry["scope"]) == (relationship, scope)


def test_a_pinned_dependency_names_only_the_version_it_pins(lock: Path) -> None:
    assert _resolved(lock)["pytest@9.1.1"]["dependencies"] == [
        "pkg:pypi/pluggy@1.6.0",
        "pkg:pypi/zope-interface@7.0",
    ]


def test_the_snapshot_names_its_commit_and_replaces_the_last_one(lock: Path) -> None:
    body = dependency_snapshot.snapshot(lock, _ENV, now=datetime(2026, 10, 21, tzinfo=UTC))
    assert (body["sha"], body["ref"]) == (_ENV["GITHUB_SHA"], "refs/heads/main")
    assert body["job"] == {"correlator": "uv-lock-backend", "id": "42"}
    assert body["scanned"] == "2026-10-21T00:00:00+00:00"


def test_the_command_writes_json_and_refuses_outside_actions(
    lock: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, value in _ENV.items():
        monkeypatch.setenv(name, value)
    assert dependency_snapshot.main(["dependency_snapshot.py", str(lock)]) == 0
    assert json.loads(capsys.readouterr().out)["version"] == 0

    monkeypatch.delenv("GITHUB_SHA")
    assert dependency_snapshot.main(["dependency_snapshot.py", str(lock)]) == 2
    assert "GITHUB_SHA is not set" in capsys.readouterr().err
    assert dependency_snapshot.main(["dependency_snapshot.py"]) == 2
