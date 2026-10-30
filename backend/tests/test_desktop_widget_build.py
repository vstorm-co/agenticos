"""Widget packaging preserves metadata and redacts signing failures."""

import importlib.util
import json
import plistlib
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "build_desktop_widget", ROOT / "scripts/build_desktop_widget.py"
)
assert spec is not None and spec.loader is not None
widget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(widget)


def test_bundle_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for relative in ("desktop/widgets", "desktop/ui", "desktop/src-tauri"):
        (tmp_path / relative).mkdir(parents=True)
    (tmp_path / "desktop/widgets/Strings.json").write_text(
        json.dumps({"pl": {"widget.ask": "Zapytaj"}})
    )
    (tmp_path / "desktop/ui/app-icon.png").write_bytes(b"logo")
    (tmp_path / "desktop/src-tauri/tauri.conf.json").write_text('{"version":"1.29.0"}')
    command = Mock(return_value="")
    monkeypatch.setattr(widget, "run", command)
    monkeypatch.setattr(widget, "sign", Mock())
    monkeypatch.setenv("TAURI_ENV_TARGET_TRIPLE", "x86_64-apple-darwin")
    bundle = widget.build(tmp_path)
    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == info["CFBundleVersion"] == "1.29.0"
    assert info["NSExtension"]["NSExtensionPointIdentifier"] == "com.apple.widgetkit-extension"
    assert (
        '"widget.ask" = "Zapytaj";'
        in (bundle / "Contents/Resources/pl.lproj/Localizable.strings").read_text()
    )
    assert "x86_64-apple-macos14.0" in command.call_args_list[0].args[0]
    assert plistlib.loads((ROOT / "desktop/widgets/Widgets.entitlements").read_bytes()) == {
        "com.apple.security.app-sandbox": True
    }
    monkeypatch.setenv("TAURI_ENV_TARGET_TRIPLE", "unsupported")
    with pytest.raises(RuntimeError, match="supports arm64 and x86_64"):
        widget.build(tmp_path)


@pytest.mark.parametrize("binary", ["security", "codesign"])
def test_signing_errors_redact_credentials(binary: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        widget.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, "", "secret-value")),
    )
    with pytest.raises(RuntimeError) as error:
        widget.run([binary, "secret-value"], {})
    assert "secret-value" not in str(error.value)


def test_signing_failure_cleans_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def command(arguments: list[str], _env: dict[str, str]) -> str:
        calls.append(arguments)
        if arguments[1] == "import":
            raise RuntimeError("import failed")
        return ""

    monkeypatch.setattr(widget, "run", command)
    with pytest.raises(RuntimeError, match="import failed"):
        widget.sign(Path("widget.appex"), Path("entitlements"), {"APPLE_CERTIFICATE": "YQ=="})
    assert calls[-1][1] == "delete-keychain"
    assert not Path(calls[-1][-1]).parent.exists()
