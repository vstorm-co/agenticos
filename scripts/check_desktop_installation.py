"""Smoke-test built desktop packages without opening or automating their UI.

macOS copies the app from a read-only DMG to a temporary Applications folder.
Windows and Linux install and uninstall only on disposable CI runners.
"""

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(*command: str) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def one(folder: Path, pattern: str) -> Path:
    files = list(folder.glob(pattern))
    if len(files) != 1:
        raise RuntimeError(f"Expected one {pattern} in {folder}, found {len(files)}")
    return files[0]


def verify_mac_app(app: Path) -> None:
    contents = app / "Contents"
    info = plistlib.loads((contents / "Info.plist").read_bytes())
    if info["CFBundleIdentifier"] != "co.vstorm.agenticos":
        raise RuntimeError("Unexpected desktop application identity")
    if not (contents / "MacOS" / info["CFBundleExecutable"]).is_file():
        raise RuntimeError("The installed app has no executable")
    widget = contents / "PlugIns/AgenticOSWidgets.appex"
    extension = plistlib.loads((widget / "Contents/Info.plist").read_bytes())
    if extension["CFBundleShortVersionString"] != info["CFBundleShortVersionString"]:
        raise RuntimeError("The widget version does not match its application")
    if extension["NSExtension"]["NSExtensionPointIdentifier"] != "com.apple.widgetkit-extension":
        raise RuntimeError("The extension is not a WidgetKit widget")
    run("codesign", "--verify", "--deep", "--strict", str(app))
    entitlements = plistlib.loads(
        run("codesign", "-d", "--entitlements", "-", "--xml", str(widget)).encode()
    )
    if entitlements != {"com.apple.security.app-sandbox": True}:
        raise RuntimeError("The launcher widget has unexpected permissions")


def macos(folder: Path) -> None:
    image = one(folder / "dmg", "*.dmg")
    with tempfile.TemporaryDirectory(prefix="agenticos-install-smoke-") as temporary:
        root = Path(temporary)
        mount = root / "image"
        mount.mkdir()
        run(
            "hdiutil",
            "attach",
            "-readonly",
            "-nobrowse",
            "-noautoopen",
            "-mountpoint",
            str(mount),
            str(image),
        )
        try:
            if not (mount / "Applications").is_symlink() or (
                mount / "Applications"
            ).readlink() != Path("/Applications"):
                raise RuntimeError("The DMG needs its Applications shortcut")
            if not (mount / ".DS_Store").is_file():
                raise RuntimeError("The DMG has no saved icon layout")
            installed = root / "Applications/AgenticOS.app"
            installed.parent.mkdir()
            shutil.copytree(mount / "AgenticOS.app", installed, symlinks=True)
            verify_mac_app(installed)
            print("MACOS_INSTALL: copied from DMG; app, widget and signatures verified")
        finally:
            run("hdiutil", "detach", str(mount))


def disposable_runner() -> None:
    if os.environ.get("CI") != "true":
        raise RuntimeError("Package installation and removal require a disposable CI runner")


def windows(folder: Path) -> None:
    disposable_runner()
    installer = one(folder / "nsis", "*-setup.exe")
    with tempfile.TemporaryDirectory(prefix="agenticos-install-smoke-") as temporary:
        destination = Path(temporary) / "AgenticOS"
        run(str(installer), "/S", f"/D={destination}")
        uninstaller = one(destination, "*ninstall*.exe")
        try:
            executables = [p for p in destination.glob("*.exe") if p != uninstaller]
            if len(executables) != 1 or executables[0].read_bytes()[:2] != b"MZ":
                raise RuntimeError("The installed Windows application is missing")
        finally:
            run(str(uninstaller), "/S")
            deadline = time.monotonic() + 30
            while executables and executables[0].exists() and time.monotonic() < deadline:
                time.sleep(0.2)
        if executables and executables[0].exists():
            raise RuntimeError("The uninstaller did not remove its executable")
        print("WINDOWS_INSTALL: per-user silent installation and removal verified")


def linux(folder: Path) -> None:
    disposable_runner()
    package = one(folder / "deb", "*.deb")
    name = run("dpkg-deb", "--field", str(package), "Package").strip()
    run("sudo", "dpkg", "--install", str(package))
    try:
        status = run("dpkg-query", "--show", "--showformat=${Status}", name)
        if status != "install ok installed":
            raise RuntimeError("The Debian package was not installed")
        paths = run("dpkg-query", "--listfiles", name).splitlines()
        if not any(p.endswith(".desktop") and Path(p).is_file() for p in paths):
            raise RuntimeError("The Linux launcher is missing")
    finally:
        run("sudo", "dpkg", "--remove", name)
    image = one(folder / "appimage", "*.AppImage")
    with tempfile.TemporaryDirectory(prefix="agenticos-appimage-") as temporary:
        subprocess.run(
            [str(image), "--appimage-extract"], cwd=temporary, check=True, capture_output=True
        )
        if not (Path(temporary) / "squashfs-root/AppRun").is_file():
            raise RuntimeError("The portable AppImage launcher is missing")
    print("LINUX_INSTALL: Debian installation/removal and AppImage extraction verified")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    folder = args.bundle.resolve()
    if sys.platform == "darwin":
        macos(folder)
    elif sys.platform == "win32":
        windows(folder)
    elif sys.platform == "linux":
        linux(folder)
    else:
        raise RuntimeError(f"Unsupported installer platform: {sys.platform}")
