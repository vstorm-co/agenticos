"""Release preparation aligns embedded app versions without changing source tags."""

import importlib.util
import json
import os
import plistlib
import shutil
import subprocess
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
    app_entitlements = apple / "app/agenticos-mobile_iOS.entitlements"
    app_entitlements.write_bytes(plistlib.dumps({}))
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
    assert plistlib.loads(app_entitlements.read_bytes())["aps-environment"] == "production"
    actual_apple = ROOT / "mobile/src-tauri/gen/apple"
    actual_entitlements = actual_apple / "agenticos-mobile_iOS/agenticos-mobile_iOS.entitlements"
    assert plistlib.loads(actual_entitlements.read_bytes())["aps-environment"] == "development"
    assert (
        "agenticos-mobile_iOS/agenticos-mobile_iOS.entitlements"
        in (actual_apple / "agenticos-mobile.xcodeproj/project.pbxproj").read_text()
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


def test_desktop_updater_manifest_has_only_one_writer() -> None:
    release = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    desktop = release["jobs"]["desktop"]
    assert desktop["strategy"]["max-parallel"] == 1
    action = next(step for step in desktop["steps"] if "includeUpdaterJson" in step.get("with", {}))
    assert action["with"]["includeUpdaterJson"] is True


def test_release_jobs_build_the_verified_commit_even_if_the_tag_moves(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    resolver = next(
        step for step in workflow["jobs"]["resolve"]["steps"] if step.get("id") == "release"
    )

    git_bin = shutil.which("git")
    bash_bin = shutil.which("bash")
    assert git_bin is not None and bash_bin is not None

    def git(*args: str) -> str:
        return subprocess.run(
            [git_bin, *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "release@example.test")
    git("config", "user.name", "Release test")
    git("commit", "--allow-empty", "-m", "verified release")
    verified = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", verified)
    git("tag", "v1.8.3")
    git("checkout", "-b", "unverified")
    git("commit", "--allow-empty", "-m", "unverified replacement")
    replacement = git("rev-parse", "HEAD")
    git("checkout", "main")
    cli = tmp_path / "bin"
    cli.mkdir()
    gh = cli / "gh"
    gh.write_text(
        '#!/bin/sh\ngit update-ref refs/tags/v1.8.3 "$REPLACEMENT_SHA"\n'
        + 'printf \'%s\' \'{"id":123,"draft":false,"prerelease":false}\'\n'
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    subprocess.run(
        [bash_bin, "-c", resolver["run"]],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{cli}{os.pathsep}{os.environ['PATH']}",
            "TAG": "v1.8.3",
            "GITHUB_REPOSITORY": "example/app",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "REPLACEMENT_SHA": replacement,
        },
    )
    assert git("rev-parse", "v1.8.3") == replacement
    assert f"commit={verified}" in output.read_text().splitlines()
    assert workflow["jobs"]["resolve"]["outputs"]["commit"] == "${{ steps.release.outputs.commit }}"
    for name in ("desktop", "android", "ios"):
        checkout = next(
            step
            for step in workflow["jobs"][name]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == "${{ needs.resolve.outputs.commit }}"


def test_desktop_smoke_packages_omit_debug_symbols_without_skipping_formats() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/apps.yml").read_text())
    job = workflow["jobs"]["desktop"]
    assert job["env"]["CARGO_PROFILE_DEV_DEBUG"] == "0"
    assert set(job["strategy"]["matrix"]["os"]) == {
        "macos-latest",
        "windows-latest",
        "ubuntu-latest",
    }
    packaging = next(
        step for step in job["steps"] if step.get("name") == "Build desktop installer packages"
    )
    assert "--debug --ci" in packaging["run"]
    assert "--bundles" not in packaging["run"]
    assert next(
        step for step in job["steps"] if step.get("name") == "Install and remove desktop packages"
    )


@pytest.mark.parametrize(
    ("private", "public", "allowed"),
    [("", "public", False), ("private", "", False), ("", "", False), ("private", "public", True)],
)
def test_release_requires_both_updater_keys_before_preparing_assets(
    tmp_path: Path, private: str, public: str, allowed: bool
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["desktop"]["steps"]
        if s.get("name") == "Prepare version and signing"
    )
    bash = shutil.which("bash")
    assert bash is not None
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (tmp_path / "desktop").mkdir()
    marker = tmp_path / "prepared"
    for command in ("python3", "rustup", "bun"):
        script = binaries / command
        script.write_text(
            "#!/bin/sh\n"
            + ('printf prepared > "$PREPARED"\n' if command == "python3" else "")
            + "exit 0\n"
        )
        script.chmod(0o755)
    result = subprocess.run(
        [bash, "-c", step["run"]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PATH": str(binaries),
            "UPDATE_KEY": private,
            "UPDATE_PUBLIC_KEY": public,
            "TAG": "v1.31.1",
            "PREPARED": str(marker),
        },
    )
    assert (result.returncode == 0) is allowed, result.stderr
    assert marker.exists() is allowed


def test_macos_release_defaults_to_ad_hoc_without_disabling_updater_signatures() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    steps = workflow["jobs"]["desktop"]["steps"]
    gate = "vars.AGENTICOS_MACOS_SIGNING_ENABLED == 'true'"
    signing = next(
        step for step in steps if step.get("name") == "Require macOS signing and notarization"
    )
    assert signing["if"] == "runner.os == 'macOS' && " + gate
    action = next(step for step in steps if "includeUpdaterJson" in step.get("with", {}))
    assert not any(name.startswith("APPLE_") for name in action["env"])
    assert signing["env"]["APPLE_CERTIFICATE"] == "${{ secrets.APPLE_CERTIFICATE }}"
    assert action["env"]["TAURI_SIGNING_PRIVATE_KEY"] == "${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}"
    assert action["with"]["includeUpdaterJson"] is True
    notice = next(
        step
        for step in steps
        if step.get("name") == "Sign macOS with the stable self-signed certificate"
    )
    assert notice["if"] == "runner.os == 'macOS' && vars.AGENTICOS_MACOS_SIGNING_ENABLED != 'true'"
    assert "Open Anyway" in notice["run"]


@pytest.mark.parametrize(
    "missing",
    [
        None,
        "APPLE_CERTIFICATE",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_TEAM_ID",
        "APPLE_ID",
        "APPLE_PASSWORD",
    ],
)
def test_enabled_macos_signing_refuses_each_missing_credential(
    tmp_path: Path, missing: str | None
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["desktop"]["steps"]
        if s.get("name") == "Require macOS signing and notarization"
    )
    env = dict.fromkeys(step["env"], "test-credential")
    if missing is not None:
        env[missing] = ""
    bash = shutil.which("bash")
    assert bash is not None
    output = tmp_path / "github-env"
    result = subprocess.run(
        [bash, "-c", step["run"]],
        env={**env, "PATH": os.environ["PATH"], "GITHUB_ENV": str(output)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (missing is None)
    assert "test-credential" not in result.stdout + result.stderr
    if missing is not None:
        assert missing in result.stdout
        assert not output.exists()
    else:
        exported = output.read_text()
        for name in env:
            assert name + "<<" in exported


def test_ad_hoc_macos_exports_only_the_ad_hoc_identity(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["desktop"]["steps"]
        if s.get("name") == "Sign macOS with the stable self-signed certificate"
    )
    output = tmp_path / "github-env"
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, "-c", step["run"]],
        env={
            "GITHUB_ENV": str(output),
            "SIGNING_P12": "",
            "SIGNING_P12_PASSWORD": "",
            "SIGNING_IDENTITY": "",
        },
        check=True,
        capture_output=True,
    )
    assert output.read_text() == "APPLE_SIGNING_IDENTITY=-\n"


def test_self_signed_macos_needs_the_identity_name_before_touching_a_keychain(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["desktop"]["steps"]
        if s.get("name") == "Sign macOS with the stable self-signed certificate"
    )
    assert set(step["env"]) == {"SIGNING_P12", "SIGNING_P12_PASSWORD", "SIGNING_IDENTITY"}
    output = tmp_path / "github-env"
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-c", step["run"]],
        env={
            "GITHUB_ENV": str(output),
            "PATH": os.environ["PATH"],
            "SIGNING_P12": "certificate",
            "SIGNING_P12_PASSWORD": "secret",
            "SIGNING_IDENTITY": "",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert "secret" not in result.stdout + result.stderr


def test_release_bundler_receives_the_same_public_key_as_the_running_app(tmp_path: Path) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    steps = workflow["jobs"]["desktop"]["steps"]
    step = next(s for s in steps if s.get("name") == "Configure updater public key")
    action = next(s for s in steps if "includeUpdaterJson" in s.get("with", {}))
    assert step["env"]["UPDATE_PUBLIC_KEY"] == action["env"]["AGENTICOS_UPDATER_PUBLIC_KEY"]
    path = tmp_path / "desktop/src-tauri/tauri.release.conf.json"
    path.parent.mkdir(parents=True)
    config = {
        "bundle": {"createUpdaterArtifacts": True},
        "plugins": {"updater": {"endpoints": ["https://example.test/latest.json"]}},
    }
    path.write_text(json.dumps(config))
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, "-c", step["run"]],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "UPDATE_PUBLIC_KEY": "release-public-key"},
        check=True,
        capture_output=True,
    )
    expected = {
        **config,
        "plugins": {"updater": {**config["plugins"]["updater"], "pubkey": "release-public-key"}},
    }
    assert json.loads(path.read_text()) == expected
    assert config["bundle"]["createUpdaterArtifacts"] is True
