"""Build the credential-free macOS launcher widget before bundling the app."""

import base64
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], env: dict[str, str]) -> str:
    """Keep signing credentials out of exceptions and command logs."""
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        detail = "" if command[0] in {"security", "codesign"} else f": {result.stderr.strip()}"
        raise RuntimeError(f"Widget build command failed: {command[0]}{detail}")
    return result.stdout


def sign(bundle: Path, entitlements: Path, env: dict[str, str]) -> None:
    certificate = env.get("APPLE_CERTIFICATE")
    if not certificate:
        identity = env.get("APPLE_SIGNING_IDENTITY", "-")
        run(
            [
                "codesign",
                "--force",
                "--sign",
                identity,
                "--entitlements",
                str(entitlements),
                "--timestamp=none" if identity == "-" else "--timestamp",
                str(bundle),
            ],
            env,
        )
        return
    with tempfile.TemporaryDirectory(prefix="agenticos-widget-sign-") as temporary:
        folder = Path(temporary)
        p12 = folder / "certificate.p12"
        p12.write_bytes(base64.b64decode(certificate, validate=True))
        p12.chmod(0o600)
        keychain = str(folder / "widget.keychain-db")
        password = os.urandom(24).hex()
        run(["security", "create-keychain", "-p", password, keychain], env)
        try:
            run(["security", "unlock-keychain", "-p", password, keychain], env)
            run(
                [
                    "security",
                    "import",
                    str(p12),
                    "-k",
                    keychain,
                    "-P",
                    env.get("APPLE_CERTIFICATE_PASSWORD", ""),
                    "-T",
                    "/usr/bin/codesign",
                ],
                env,
            )
            run(
                [
                    "security",
                    "set-key-partition-list",
                    "-S",
                    "apple-tool:,apple:,codesign:",
                    "-s",
                    "-k",
                    password,
                    keychain,
                ],
                env,
            )
            identities = run(
                ["security", "find-identity", "-v", "-p", "codesigning", keychain], env
            )
            matches = re.findall(
                r'\b([0-9A-Fa-f]{40})\s+"Developer ID Application:[^"\n]+"', identities
            )
            if len(matches) != 1:
                raise RuntimeError("The widget needs exactly one Developer ID Application identity")
            run(
                [
                    "codesign",
                    "--force",
                    "--sign",
                    matches[0],
                    "--keychain",
                    keychain,
                    "--options",
                    "runtime",
                    "--entitlements",
                    str(entitlements),
                    "--timestamp",
                    str(bundle),
                ],
                env,
            )
        finally:
            run(["security", "delete-keychain", keychain], env)


def build(root: Path = ROOT) -> Path:
    env = dict(os.environ)
    developer = Path("/Applications/Xcode.app/Contents/Developer")
    if "DEVELOPER_DIR" not in env and developer.exists():
        env["DEVELOPER_DIR"] = str(developer)
    target = env.get("TAURI_ENV_TARGET_TRIPLE", env.get("CARGO_BUILD_TARGET", platform.machine()))
    arch = (
        "arm64"
        if target.startswith(("aarch64", "arm64"))
        else "x86_64"
        if target.startswith("x86_64")
        else None
    )
    if arch is None:
        raise RuntimeError("The macOS widget supports arm64 and x86_64 builds")
    source = root / "desktop/widgets"
    bundle = root / "desktop/.widget-build/AgenticOSWidgets.appex"
    if bundle.exists():
        shutil.rmtree(bundle)
    contents = bundle / "Contents"
    binary = contents / "MacOS/AgenticOSWidgets"
    binary.parent.mkdir(parents=True)
    resources = contents / "Resources"
    resources.mkdir()
    config = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text())
    info = {
        "CFBundleIdentifier": "co.vstorm.agenticos.widgets",
        "CFBundleName": "AgenticOSWidgets",
        "CFBundleDisplayName": "AgenticOS",
        "CFBundleExecutable": binary.name,
        "CFBundlePackageType": "XPC!",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": config["version"],
        "CFBundleVersion": config["version"],
        "CFBundleDevelopmentRegion": "en",
        "LSMinimumSystemVersion": "14.0",
        "NSExtension": {"NSExtensionPointIdentifier": "com.apple.widgetkit-extension"},
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    shutil.copyfile(root / "desktop/ui/app-icon.png", resources / "WidgetMark.png")
    translations = json.loads((source / "Strings.json").read_text())
    for locale, messages in translations.items():
        folder = resources / f"{locale}.lproj"
        folder.mkdir()
        folder.joinpath("Localizable.strings").write_text(
            "\n".join(
                f"{json.dumps(key)} = {json.dumps(value, ensure_ascii=False)};"
                for key, value in messages.items()
            )
            + "\n"
        )
    run(
        [
            "xcrun",
            "--sdk",
            "macosx",
            "swiftc",
            "-O",
            "-application-extension",
            "-parse-as-library",
            "-target",
            f"{arch}-apple-macos14.0",
            "-framework",
            "SwiftUI",
            "-framework",
            "WidgetKit",
            str(source / "QuickActions.swift"),
            "-o",
            str(binary),
        ],
        env,
    )
    sign(bundle, source / "Widgets.entitlements", env)
    run(["codesign", "--verify", "--strict", str(bundle)], env)
    return bundle


if __name__ == "__main__":
    print(build())
