"""Set a release build's shell versions without modifying the source release."""

import json
import os
import plistlib
import re
import sys
from pathlib import Path


def prepare(root: Path, tag: str) -> None:
    """Validate the release version and align Tauri, Cargo and Apple versions."""
    if re.fullmatch(r"v1\.\d+\.\d+", tag) is None:
        raise ValueError("App releases use a stable v1.MINOR.PATCH platform tag")
    version = tag[1:]
    build = os.environ.get("BUILD_NUMBER", version)
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", build) is None:
        raise ValueError("Invalid Apple build number")
    for app in ("desktop", "mobile"):
        folder = root / app / "src-tauri"
        config = folder / "tauri.conf.json"
        value = json.loads(config.read_text())
        value["version"] = version
        config.write_text(json.dumps(value, indent=2) + "\n")
        manifest = folder / "Cargo.toml"
        source = manifest.read_text()
        source, count = re.subn(
            r'(?m)^version = "[^"]+"$', f'version = "{version}"', source, count=1
        )
        if count != 1:
            raise ValueError(f"No package version in {manifest}")
        manifest.write_text(source)
        lock = folder / "Cargo.lock"
        package = "agenticos-desktop" if app == "desktop" else "agenticos-mobile"
        source, count = re.subn(
            r'(name = "' + package + r'"\nversion = ")[^"]+',
            lambda match: match[1] + version,
            lock.read_text(),
            count=1,
        )
        if count != 1:
            raise ValueError(f"No shell package in {lock}")
        lock.write_text(source)
    apple = root / "mobile/src-tauri/gen/apple"
    project = apple / "project.yml"
    source = project.read_text()
    source = re.sub(r"(?m)^(    MARKETING_VERSION: ).*$", lambda m: m[1] + version, source)
    source = re.sub(
        r"(?m)^(    CURRENT_PROJECT_VERSION: ).*$", lambda m: m[1] + f'"{build}"', source
    )
    source = re.sub(
        r"(?m)^(        CFBundleShortVersionString: ).*$", lambda m: m[1] + version, source
    )
    source = re.sub(r"(?m)^(        CFBundleVersion: ).*$", lambda m: m[1] + f'"{build}"', source)
    source = source.replace("aps-environment: development", "aps-environment: production")
    project.write_text(source)
    for path in apple.rglob("project.pbxproj"):
        source = path.read_text()
        source = re.sub(r"(MARKETING_VERSION = )[^;]+;", lambda m: m[1] + version + ";", source)
        source = re.sub(r"(CURRENT_PROJECT_VERSION = )[^;]+;", lambda m: m[1] + build + ";", source)
        path.write_text(source)
    for path in apple.rglob("Info.plist"):
        value = plistlib.loads(path.read_bytes())
        # All embedded extensions must match the containing application's build.
        value["CFBundleShortVersionString"] = version
        value["CFBundleVersion"] = build
        path.write_bytes(plistlib.dumps(value))
    for path in apple.rglob("*.entitlements"):
        value = plistlib.loads(path.read_bytes())
        if "aps-environment" in value or path.name == "agenticos-mobile_iOS.entitlements":
            value["aps-environment"] = "production"
            path.write_bytes(plistlib.dumps(value))


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[1], sys.argv[1])
