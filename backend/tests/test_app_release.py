"""Release preparation aligns embedded app versions without changing source tags."""

import importlib.util
import json
import plistlib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_release_versions_include_apple_extensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "prepare_app_release", ROOT / "scripts/prepare_app_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for app in ("desktop", "mobile"):
        folder = tmp_path / app / "src-tauri"
        folder.mkdir(parents=True)
        (folder / "tauri.conf.json").write_text('{"version":"0.1.0"}')
        (folder / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
        (folder / "Cargo.lock").write_text(
            f'[[package]]\nname = "agenticos-{app}"\nversion = "0.1.0"\n'
        )
    apple = tmp_path / "mobile/src-tauri/gen/apple"
    apple.mkdir(parents=True)
    (apple / "project.yml").write_text(
        '    MARKETING_VERSION: 0.1.0\n    CURRENT_PROJECT_VERSION: "0.1.0"\n        CFBundleVersion: "0.1.0"\n        aps-environment: development\n'
    )
    for target in ("app", "widgets", "share"):
        folder = apple / target
        folder.mkdir()
        (folder / "Info.plist").write_bytes(plistlib.dumps({"CFBundleVersion": "old"}))
        (folder / "project.pbxproj").write_text(
            "MARKETING_VERSION = 0.1.0;\nCURRENT_PROJECT_VERSION = 0.1.0;"
        )
    (apple / "app/app.entitlements").write_bytes(plistlib.dumps({"aps-environment": "development"}))
    monkeypatch.setenv("BUILD_NUMBER", "412")
    module.prepare(tmp_path, "v1.8.3")
    assert (
        json.loads((tmp_path / "desktop/src-tauri/tauri.conf.json").read_text())["version"]
        == "1.8.3"
    )
    for target in ("app", "widgets", "share"):
        info = plistlib.loads((apple / target / "Info.plist").read_bytes())
        assert info == {"CFBundleVersion": "412", "CFBundleShortVersionString": "1.8.3"}
        assert "CURRENT_PROJECT_VERSION = 412;" in (apple / target / "project.pbxproj").read_text()
    assert (
        plistlib.loads((apple / "app/app.entitlements").read_bytes())["aps-environment"]
        == "production"
    )
    with pytest.raises(ValueError, match="stable"):
        module.prepare(tmp_path, "v1.8.3-beta.1")
    monkeypatch.setenv("BUILD_NUMBER", "invalid")
    with pytest.raises(ValueError, match="build number"):
        module.prepare(tmp_path, "v1.8.3")


def test_homebrew_cask_hashes_both_architectures_and_refuses_ambiguity(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "homebrew_cask", ROOT / "scripts/homebrew_cask.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for arch in ("aarch64", "x64"):
        (tmp_path / f"AgenticOS_1.8.3_{arch}.dmg").write_bytes(b"verified artifact")
    result = module.cask(tmp_path, "v1.8.3")
    assert result.count("sha256") == 2
    assert 'version "1.8.3"' in result
    assert "AgenticOS_1.8.3_aarch64.dmg" in result
    (tmp_path / "duplicate_aarch64.dmg").write_bytes(b"other")
    with pytest.raises(ValueError, match="exactly one"):
        module.cask(tmp_path, "v1.8.3")


def test_mobile_publication_is_opt_in_without_disabling_ci_builds() -> None:
    release = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    builds = yaml.safe_load((ROOT / ".github/workflows/apps.yml").read_text())
    mobile_gate = "vars.AGENTICOS_MOBILE_RELEASES_ENABLED == 'true'"
    assert release["jobs"]["android"]["if"] == mobile_gate
    assert release["jobs"]["ios"]["if"] == (
        mobile_gate + " && vars.AGENTICOS_TESTFLIGHT_ENABLED == 'true'"
    )
    assert "AGENTICOS_MOBILE_RELEASES_ENABLED" not in str(release["jobs"]["desktop"])
    for platform in ("android", "ios"):
        job = builds["jobs"][platform]
        assert "if" not in job
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        if platform == "android":
            assert "tauri android build --debug" in commands
        else:
            assert "--target aarch64-sim --no-sign" in commands
