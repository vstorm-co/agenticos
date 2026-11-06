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
    # An unnotarized app installed by Homebrew keeps its quarantine flag, which
    # makes Gatekeeper refuse it, so the cask clears it from the installed app.
    assert 'args: ["-dr", "com.apple.quarantine", "#{appdir}/AgenticOS.app"]' in result
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
    assert "max-parallel" not in desktop["strategy"]
    action = next(step for step in desktop["steps"] if "uploadUpdaterJson" in step.get("with", {}))
    updater = release["jobs"]["updater"]
    assert set(updater["needs"]) == {"resolve", "desktop"}
    assert "if" not in updater
    assert action["with"]["uploadUpdaterSignatures"] is True
    publishers = [
        name
        for name, job in release["jobs"].items()
        if any(
            'gh release upload "$TAG" "$RUNNER_TEMP/latest.json"' in step.get("run", "")
            for step in job["steps"]
        )
    ]
    assert publishers == ["updater"]


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
    action = next(step for step in steps if "uploadUpdaterJson" in step.get("with", {}))
    assert not any(name.startswith("APPLE_") for name in action["env"])
    assert signing["env"]["APPLE_CERTIFICATE"] == "${{ secrets.APPLE_CERTIFICATE }}"
    assert action["env"]["TAURI_SIGNING_PRIVATE_KEY"] == "${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}"
    assert action["with"]["uploadUpdaterJson"] is False
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
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/macos_signing_identity.txt").write_text("# unpinned test distribution\n")
    output = tmp_path / "github-env"
    bash = shutil.which("bash")
    assert bash is not None
    subprocess.run(
        [bash, "-c", step["run"]],
        cwd=tmp_path,
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
    # The identity must prove it can sign before the build depends on it.
    assert step["run"].index("codesign --force --sign") < step["run"].index(
        "APPLE_SIGNING_IDENTITY=$SIGNING_IDENTITY"
    )
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
    action = next(s for s in steps if "uploadUpdaterJson" in s.get("with", {}))
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


@pytest.mark.parametrize("push_fails", [False, True])
def test_tap_deploy_key_is_scoped_and_removed_even_when_publishing_fails(
    tmp_path: Path,
    push_fails: bool,
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["homebrew"]["steps"]
        if s.get("name") == "Publish the cask to the Homebrew tap"
    )
    assert step["env"].get("GH_META_TOKEN") == "${{ github.token }}"
    tools = tmp_path / "bin"
    tools.mkdir()
    git = tools / "git"
    git.write_text("""#!/bin/sh
case "$1" in
  clone)
    hosts=$(cat "$RUNNER_TEMP/tap_known_hosts")
    test "$hosts" = "github.com ssh-ed25519 public-host-key" || exit 1
    mkdir -p "$3" ;;
  diff) exit 1 ;;
  push) test "$PUSH_FAILS" = "false" ;;
esac
""")
    curl = tools / "curl"
    # Anonymous API access can be refused on a shared runner IP.
    curl.write_text("#!/bin/sh\nexit 22\n")
    gh = tools / "gh"
    gh.write_text("""#!/bin/sh
test "$1 $2" = "api meta" || exit 1
test "$GH_TOKEN" = "test-metadata-token" || exit 1
printf '%s\\n' 'github.com ssh-ed25519 public-host-key'
""")
    for tool in (git, curl, gh):
        tool.chmod(0o700)
    (tmp_path / "agenticos.rb").write_text("cask 'agenticos'\n")
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, "-c", step["run"]],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "TAP_DEPLOY_KEY": "test-private-deploy-key",
            "GH_TOKEN": "",
            "GH_META_TOKEN": "test-metadata-token",
            "TAG": "v1.35.0",
            "PUSH_FAILS": str(push_fails).lower(),
        },
    )
    assert (result.returncode != 0) == push_fails
    assert not (tmp_path / "tap_deploy_key").exists()
    assert not (tmp_path / "tap_known_hosts").exists()
    assert "test-private-deploy-key" not in result.stdout + result.stderr
    assert "test-metadata-token" not in result.stdout + result.stderr
    assert (tmp_path / "tap/Casks/agenticos.rb").read_text() == "cask 'agenticos'\n"


@pytest.mark.parametrize(
    "certificate", [b"trusted signing certificate", b"impostor certificate", None]
)
def test_installer_authenticates_certificate_bytes_not_designated_requirement(
    tmp_path: Path, certificate: bytes | None
) -> None:
    trusted = b"trusted signing certificate"
    pinned = "a619e028e78dfdff7635345c37bb4be891f5ac47"
    tools = tmp_path / "tools"
    tools.mkdir()
    codesign = tools / "codesign"
    codesign.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "--verify" ]; then exit 0; fi\n'
        'if [[ "$2" == --extract-certificates=* ]]; then\n'
        '  [ -f "$CERTIFICATE" ] || exit 1\n'
        '  prefix="${2#*=}"; cp "$CERTIFICATE" "${prefix}0"\n'
        "  exit 0\n"
        "fi\n"
        # A malicious signer can include the trusted pin in a requirement it authors.
        'echo "designated => identifier evil or certificate root = H\\"$pinned\\"" >&2\n'
    )
    codesign.chmod(0o755)
    cert = tmp_path / "certificate"
    if certificate is not None:
        cert.write_bytes(certificate)
    installer = (ROOT / "scripts/install_macos.sh").read_text()
    check = installer.split('if [ -n "$pinned" ]; then\n', 1)[1].split("\nelse\n", 1)[0]
    result = subprocess.run(
        ["/bin/bash", "-euo", "pipefail", "-c", check],
        env={
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "CERTIFICATE": str(cert),
            "pinned": pinned,
            "mount": str(tmp_path),
            "work": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (certificate == trusted), result.stderr


def test_releases_only_read_dependency_caches_seeded_by_native_ci() -> None:
    release = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    apps = yaml.safe_load((ROOT / ".github/workflows/apps.yml").read_text())
    for name in ("desktop", "android", "ios"):
        steps = release["jobs"][name]["steps"]
        cache_steps = [step for step in steps if step.get("uses", "").startswith("actions/cache")]
        assert len(cache_steps) == 1
        restore = cache_steps[0]
        assert restore["uses"].startswith("actions/cache/restore@")
        seed = next(
            step
            for step in apps["jobs"][name]["steps"]
            if step.get("name") == "Cache Cargo downloads for CI and releases"
        )
        assert seed["uses"].startswith("actions/cache@")
        assert restore["with"] == seed["with"]
        assert "target" not in restore["with"]["path"]


@pytest.mark.parametrize("pin", ["351ec21dde69acfb29f5d2661b27c0f6a517035a", "", "malformed"])
def test_pinned_releases_refuse_missing_signing_material(tmp_path: Path, pin: str) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["desktop"]["steps"]
        if s.get("name") == "Sign macOS with the stable self-signed certificate"
    )
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/macos_signing_identity.txt").write_text("# Publisher pin\n" + pin + "\n")
    env_file = tmp_path / "github-env"
    env_file.touch()
    result = subprocess.run(
        ["/bin/bash", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "SIGNING_P12": "", "GITHUB_ENV": str(env_file)},
        capture_output=True,
        text=True,
    )
    assert (result.returncode != 0) is bool(pin)
    if pin:
        assert "MACOS_SELF_SIGNED_P12 is missing" in result.stdout
        assert env_file.read_text() == ""
    else:
        assert "APPLE_SIGNING_IDENTITY=-" in env_file.read_text()


@pytest.mark.parametrize("failure", [None, "signer", "signature", "certificate", "pin", "attach"])
def test_homebrew_authenticates_assets_before_publishing_checksums(
    tmp_path: Path, failure: str | None
) -> None:
    trusted = b"trusted publisher certificate"
    cert = tmp_path / "certificate"
    cert.write_bytes(b"impostor" if failure == "signer" else trusted)
    pin = tmp_path / "pin"
    pin.write_text("malformed" if failure == "pin" else "114d1d66465f9e2174313defbbeb59639eafeeef")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "hdiutil").write_text("""#!/bin/bash
if [ "$1" = attach ]; then
  [ "$FAILURE" != attach ] || exit 1
  mkdir -p "$4/AgenticOS.app"
else
  printf '%s' "$2" > "$DETACHED"
fi
""")
    (tools / "codesign").write_text("""#!/bin/bash
if [ "$1" = --verify ]; then
  [ "$FAILURE" != signature ]
else
  [ "$FAILURE" != certificate ] || exit 1
  cp "$CERTIFICATE" "${2#*=}0"
fi
""")
    for tool in tools.iterdir():
        tool.chmod(0o700)
    detached = tmp_path / "detached"
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, str(ROOT / "scripts/verify_macos_dmg.sh"), "asset.dmg", str(pin)],
        env={
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "FAILURE": failure or "",
            "CERTIFICATE": str(cert),
            "DETACHED": str(detached),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (failure is None), result.stderr
    if failure == "pin":
        assert not detached.exists()
    else:
        mount = Path(detached.read_text())
        assert not mount.parent.exists()

    workflow = yaml.safe_load((ROOT / ".github/workflows/app-release.yml").read_text())
    job = workflow["jobs"]["homebrew"]
    assert job["runs-on"] == "macos-latest"
    attach = next(
        s for s in job["steps"] if s.get("name") == "Attach the cask for both Mac architectures"
    )
    commands = attach["run"]
    assert commands.index("verify_macos_dmg.sh") < commands.index("homebrew_cask.py")
    assert 'for dmg in "$RUNNER_TEMP"/dmgs/*.dmg' in commands
