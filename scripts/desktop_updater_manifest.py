"""Generate a complete updater manifest after every desktop build has succeeded."""

import json
import re
import sys
from pathlib import Path
from typing import TypedDict
from urllib.parse import quote


class Platform(TypedDict):
    signature: str
    url: str


class Manifest(TypedDict):
    version: str
    notes: str
    pub_date: str
    platforms: dict[str, Platform]


def manifest(release_file: Path, signatures: Path) -> Manifest:
    """Require the four native targets and their uploaded signatures before publishing.

    Release assets are independent uploads; only this final writer publishes
    latest.json. Build outputs never merge an existing, potentially partial manifest.
    """
    release: object = json.loads(release_file.read_text())
    if not isinstance(release, dict):
        raise TypeError("Expected a release object")
    tag = release.get("tag_name")
    date = release.get("published_at")
    notes = release.get("body")
    assets = release.get("assets")
    if not isinstance(tag, str) or re.fullmatch(r"v1\.\d+\.\d+", tag) is None:
        raise ValueError("Expected a stable platform release tag")
    if not isinstance(date, str) or not date or not isinstance(notes, str):
        raise ValueError("Expected published release date and notes")
    if release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("Expected a published stable release")
    if not isinstance(assets, list):
        raise TypeError("Expected release assets")
    downloads: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            raise TypeError("Expected an asset object")
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if not isinstance(name, str) or Path(name).name != name or not isinstance(url, str):
            raise ValueError("Invalid release asset")
        expected = f"https://github.com/vstorm-co/agenticos/releases/download/{tag}/{quote(name)}"
        if url != expected or name in downloads:
            raise ValueError(f"Invalid or duplicate download URL for {name}")
        downloads[name] = url
    version = tag[1:]
    # Match the pinned action's default: MSI is the default Windows updater.
    bundles = {
        "darwin-aarch64": (f"AgenticOS_{version}_aarch64.app.tar.gz", "app"),
        "darwin-x86_64": (f"AgenticOS_{version}_x64.app.tar.gz", "app"),
        "linux-x86_64": (f"AgenticOS_{version}_amd64.AppImage", "appimage"),
        "windows-x86_64": (f"AgenticOS_{version}_x64_en-US.msi", "msi"),
    }
    platforms: dict[str, Platform] = {}
    for platform, (name, installer) in bundles.items():
        if name not in downloads or name + ".sig" not in downloads:
            raise ValueError(f"Missing signed updater for {platform}: {name}")
        signature = (signatures / (name + ".sig")).read_text().strip()
        if not signature:
            raise ValueError(f"Empty updater signature for {platform}")
        entry: Platform = {"url": downloads[name], "signature": signature}
        platforms[platform] = entry
        platforms[f"{platform}-{installer}"] = entry
    # Keep the installer-specific endpoints already published by tauri-action.
    installers = {
        "windows-x86_64-nsis": f"AgenticOS_{version}_x64-setup.exe",
        "linux-x86_64-deb": f"AgenticOS_{version}_amd64.deb",
        "linux-x86_64-rpm": f"AgenticOS-{version}-1.x86_64.rpm",
    }
    for platform, name in installers.items():
        if name not in downloads:
            continue
        if name + ".sig" not in downloads:
            raise ValueError(f"Missing signature for {platform}")
        signature = (signatures / (name + ".sig")).read_text().strip()
        if not signature:
            raise ValueError(f"Empty signature for {platform}")
        platforms[platform] = {"url": downloads[name], "signature": signature}
    return {"version": version, "notes": notes, "pub_date": date, "platforms": platforms}


if __name__ == "__main__":
    print(json.dumps(manifest(Path(sys.argv[1]), Path(sys.argv[2])), indent=2))
