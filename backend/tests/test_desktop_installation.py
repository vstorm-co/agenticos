"""Installer validation refuses ambiguous packages and destructive local runs."""

import importlib.util
import os
import plistlib
import shlex
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "check_desktop_installation", ROOT / "scripts/check_desktop_installation.py"
)
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_ambiguous_or_missing_packages_are_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Expected one"):
        installer.one(tmp_path, "*.dmg")
    (tmp_path / "one.dmg").touch()
    assert installer.one(tmp_path, "*.dmg").name == "one.dmg"
    (tmp_path / "two.dmg").touch()
    with pytest.raises(RuntimeError, match="found 2"):
        installer.one(tmp_path, "*.dmg")


def test_windows_and_linux_installation_requires_a_disposable_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    for check in (installer.windows, installer.linux):
        with pytest.raises(RuntimeError, match="disposable CI runner"):
            check(tmp_path)


@pytest.mark.parametrize(
    "library",
    [
        "libwayland-client.so",
        "libwayland-client.so.0",
        "libwayland-client.so.0.23.0",
    ],
)
def test_appimage_rejects_bundled_wayland_clients_in_nested_library_directories(
    tmp_path: Path, library: str
) -> None:
    (tmp_path / "AppRun").touch()
    bundled = tmp_path / "usr/lib/x86_64-linux-gnu" / library
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    with pytest.raises(RuntimeError, match=library):
        installer.verify_appimage_tree(tmp_path)


def test_appimage_rejects_wayland_symlinks_even_when_their_target_is_missing(
    tmp_path: Path,
) -> None:
    (tmp_path / "AppRun").touch()
    (tmp_path / "libwayland-client.so.0").symlink_to("libwayland-client.so.0.23.0")
    with pytest.raises(RuntimeError, match="host Wayland client"):
        installer.verify_appimage_tree(tmp_path)


def test_appimage_requires_a_launcher_but_allows_application_libraries(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="launcher is missing"):
        installer.verify_appimage_tree(tmp_path)
    (tmp_path / "AppRun").touch()
    (tmp_path / "libwebkit2gtk-4.1.so.0").touch()
    installer.verify_appimage_tree(tmp_path)


@pytest.mark.parametrize("bundled_wayland", [False, True])
def test_appimage_extraction_validates_payload_and_cleans_up(
    tmp_path: Path, bundled_wayland: bool
) -> None:
    images = tmp_path / "appimage"
    images.mkdir()
    image = images / "AgenticOS.AppImage"
    # A small executable fixture exercises extraction and validation together
    # without needing a Linux AppImage runtime on the developer's machine.
    image.write_text(
        "#!/bin/sh\n"
        'test "$1" = "--appimage-extract" || exit 1\n'
        "mkdir -p squashfs-root/usr/lib\n"
        "touch squashfs-root/AppRun\n"
        + ("touch squashfs-root/usr/lib/libwayland-client.so.0\n" if bundled_wayland else "")
        + f"pwd > {shlex.quote(str(tmp_path / 'extraction-directory'))}\n"
    )
    image.chmod(0o755)
    if bundled_wayland:
        with pytest.raises(RuntimeError, match="host Wayland client"):
            installer.appimage(tmp_path)
    else:
        installer.appimage(tmp_path)
    extracted = Path((tmp_path / "extraction-directory").read_text().strip())
    assert not extracted.exists()


def test_appimage_extraction_errors_are_not_reported_as_success(tmp_path: Path) -> None:
    images = tmp_path / "appimage"
    images.mkdir()
    image = images / "AgenticOS.AppImage"
    image.write_text("#!/bin/sh\nexit 7\n")
    image.chmod(0o755)
    with pytest.raises(subprocess.CalledProcessError) as error:
        installer.appimage(tmp_path)
    assert error.value.returncode == 7


@pytest.mark.parametrize(("build_status", "check_status"), [(0, 0), (9, 0), (0, 7)])
def test_linux_release_stops_on_build_or_appimage_validation_failure(
    tmp_path: Path, build_status: int, check_status: int
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, status in (("bunx", build_status), ("python3", check_status)):
        tool = tools / name
        tool.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "$COMMAND_LOG/{name}"\nexit {status}\n')
        tool.chmod(0o755)
    arguments = ["build", "--target", "x86_64-unknown-linux-gnu", "--", "--locked"]
    bash = shutil.which("bash")
    assert bash is not None
    result = subprocess.run(
        [bash, str(ROOT / "scripts/build_linux_desktop_release.sh"), *arguments],
        cwd=tmp_path,
        env=os.environ
        | {"PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "COMMAND_LOG": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == (build_status or check_status)
    assert (tmp_path / "bunx").read_text().splitlines() == ["tauri", *arguments]
    if build_status:
        assert not (tmp_path / "python3").exists()
    else:
        assert (tmp_path / "python3").read_text().splitlines() == [
            "../scripts/check_desktop_installation.py",
            "src-tauri/target/x86_64-unknown-linux-gnu/release/bundle",
            "--appimage-only",
        ]


@pytest.mark.security
def test_mac_validation_rejects_mismatched_extensions_and_unexpected_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "AgenticOS.app"
    contents = app / "Contents"
    binary = contents / "MacOS/agenticos-desktop"
    binary.parent.mkdir(parents=True)
    binary.touch()
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "co.vstorm.agenticos",
                "CFBundleExecutable": binary.name,
                "CFBundleShortVersionString": "1.29.0",
            }
        )
    )
    widget = contents / "PlugIns/AgenticOSWidgets.appex/Contents"
    widget.mkdir(parents=True)
    extension = {
        "CFBundleShortVersionString": "1.28.0",
        "NSExtension": {"NSExtensionPointIdentifier": "com.apple.widgetkit-extension"},
    }
    (widget / "Info.plist").write_bytes(plistlib.dumps(extension))
    with pytest.raises(RuntimeError, match="version does not match"):
        installer.verify_mac_app(app)
    extension["CFBundleShortVersionString"] = "1.29.0"
    (widget / "Info.plist").write_bytes(plistlib.dumps(extension))
    monkeypatch.setattr(
        installer,
        "run",
        Mock(
            return_value=plistlib.dumps(
                {"com.apple.security.app-sandbox": True, "unexpected": True}
            ).decode()
        ),
    )
    with pytest.raises(RuntimeError, match="unexpected permissions"):
        installer.verify_mac_app(app)


@pytest.mark.parametrize(
    "library", ["libwayland-cursor.so.0", "libwayland-egl.so.1", "libwayland-server.so.0"]
)
def test_appimage_allows_wayland_helpers_that_do_not_replace_the_host_client(
    tmp_path: Path,
    library: str,
) -> None:
    (tmp_path / "AppRun").touch()
    bundled = tmp_path / "usr/lib" / library
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    installer.verify_appimage_tree(tmp_path)
