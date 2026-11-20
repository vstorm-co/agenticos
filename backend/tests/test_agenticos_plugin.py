"""The plugin guard rejects tool drift and broken package resources."""

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "plugin_guard", ROOT / "scripts/check_agenticos_plugin.py"
)
assert _spec is not None and _spec.loader is not None
plugin_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin_guard)


@pytest.fixture
def package(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "plugins", tmp_path / "plugins")
    shutil.copytree(ROOT / ".claude-plugin", tmp_path / ".claude-plugin")
    target = tmp_path / "backend/app/services/platform_mcp"
    target.mkdir(parents=True)
    for name in [
        "_tools.py",
        "_lifecycle.py",
        "_details.py",
        "_disclosure.py",
        "_administration.py",
    ]:
        shutil.copyfile(ROOT / "backend/app/services/platform_mcp" / name, target / name)
    return tmp_path


def test_shipped_plugin_matches_the_server() -> None:
    assert plugin_guard.check(ROOT) == []


def test_guard_reports_missing_and_invented_tools(package: Path) -> None:
    page = package / plugin_guard.MAP
    page.write_text(page.read_text().replace("| `whoami` |", "| `invented_tool` |"))
    errors = plugin_guard.check(package)
    assert any("missing" in error and "whoami" in error for error in errors)
    assert any("Unregistered" in error and "invented_tool" in error for error in errors)


def test_guard_reports_bad_json_and_broken_local_links(package: Path) -> None:
    (package / "plugins/agenticos/compatibility.json").write_text("{")
    skill = package / "plugins/agenticos/skills/operating-agenticos/SKILL.md"
    skill.write_text(skill.read_text() + "\n[Missing](reference/missing.md)\n")
    errors = plugin_guard.check(package)
    assert any("compatibility.json" in error for error in errors)
    assert any("missing.md" in error for error in errors)
