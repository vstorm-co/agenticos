"""Native Arch packaging uses the exact source commit and pacman's update ownership."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["/usr/bin/git", "-C", str(repo), *args], text=True).strip()


@pytest.mark.parametrize("build_status", [0, 1])
def test_package_recipe_checksums_the_committed_source_and_propagates_build_failure(
    tmp_path: Path, build_status: int
) -> None:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Packaging test")
    (repo / "backend").mkdir()
    (repo / "backend/pyproject.toml").write_text('[project]\nversion = "1.82.2"\n')
    (repo / "packaging/arch").mkdir(parents=True)
    (repo / "packaging/arch/PKGBUILD.in").write_text(
        (ROOT / "packaging/arch/PKGBUILD.in").read_text()
    )
    (repo / "marker.txt").write_text("committed source")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "source")
    (repo / "marker.txt").write_text("uncommitted mutation")
    output = tmp_path / "packages"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # makepkg is the external Arch boundary. Archive generation and checksumming are real.
    makepkg = fake_bin / "makepkg"
    makepkg.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys\nfrom pathlib import Path\n"
        "p=Path(os.environ['CALLS']); calls=json.loads(p.read_text()) if p.exists() else []\n"
        "calls.append(sys.argv[1:]);p.write_text(json.dumps(calls))\n"
        "sys.exit(int(os.environ['BUILD_STATUS']) if '--cleanbuild' in sys.argv else 0)\n"
    )
    makepkg.chmod(0o755)
    calls_path = tmp_path / "calls.json"
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/build_arch_package.sh"), str(output)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls_path),
            "BUILD_STATUS": str(build_status),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == build_status, result.stderr
    archive = output / "agenticos-1.82.2.tar.gz"
    with tarfile.open(archive) as source:
        marker = source.extractfile("agenticos-1.82.2/marker.txt")
        assert marker is not None
        assert marker.read() == b"committed source"
    recipe = (output / "PKGBUILD").read_text()
    assert "pkgver=1.82.2" in recipe
    assert hashlib.sha256(archive.read_bytes()).hexdigest() in recipe
    assert "@VERSION@" not in recipe and "@SHA256@" not in recipe
    calls = json.loads(calls_path.read_text())
    assert calls[0] == ["--cleanbuild", "--noconfirm"]
    assert len(calls) == (2 if build_status == 0 else 1)


def test_arch_validation_refuses_destructive_work_outside_ci(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(ROOT / "scripts/check_arch_package.sh"), str(tmp_path)],
        env={**os.environ, "CI": "false"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode != 0


def test_arch_build_retains_package_manager_ownership_and_real_render_check() -> None:
    recipe = (ROOT / "packaging/arch/PKGBUILD.in").read_text()
    assert "--release --locked --features arch-package" in recipe
    assert "'webkit2gtk-4.1'" in recipe
    assert "libwayland-client.so" not in recipe
    updater = (ROOT / "desktop/src-tauri/src/updater.rs").read_text()
    assert updater.index('feature = "arch-package"') < updater.index(".updater()")
    assert "sudo pacman -U" in updater
    entry = (ROOT / "desktop/src-tauri/src/lib.rs").read_text()
    assert 'arg == "--installation-smoke"' in entry
    assert "native_browser_smoke::run();" in entry
    render = (ROOT / "scripts/arch_render_smoke.sh").read_text()
    assert "GDK_BACKEND=x11 agenticos --installation-smoke" in render
    assert (
        "GDK_BACKEND=wayland WAYLAND_DISPLAY=agenticos-smoke agenticos --installation-smoke"
        in render
    )
    smoke = (ROOT / "desktop/src-tauri/src/native_browser_smoke.rs").read_text()
    assert '"Runtime.evaluate"' in smoke
    assert "app.exit(if result.is_ok() { 0 } else { 1 })" in smoke


def test_runtime_validation_uses_a_fresh_base_without_build_dependencies() -> None:
    workflow = (ROOT / ".github/workflows/arch-package.yml").read_text()
    build, runtime = workflow.split("  validate:\n", 1)
    assert "archlinux:base-devel@sha256:" in build
    assert "archlinux:base@sha256:" in runtime
    assert "needs: build" in runtime
    assert 'pacman -Q "$PACKAGE"' in runtime
    assert "rust clang base-devel" in runtime
    assert "actions/download-artifact@" in runtime
    assert runtime.index("check_arch_package.sh") < runtime.index("gh release upload")
    check = (ROOT / "scripts/check_arch_package.sh").read_text()
    assert "makepkg" not in check
    assert 'pacman -U --noconfirm "$PACKAGE"' in check
    assert 'pacman -U --noconfirm "$UPGRADE"' in check
