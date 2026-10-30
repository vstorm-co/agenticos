"""Installer validation refuses ambiguous packages and destructive local runs."""

import importlib.util
import plistlib
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
