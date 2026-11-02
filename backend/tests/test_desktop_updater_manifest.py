"""A parallel desktop release publishes a complete manifest or publishes nothing."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "broken",
    [None, "asset", "signature-asset", "signature-file", "empty", "duplicate", "url", "version"],
)
def test_manifest_is_complete_or_fails(tmp_path: Path, broken: str | None) -> None:
    names = [
        "AgenticOS_1.8.3_aarch64.app.tar.gz",
        "AgenticOS_1.8.3_x64.app.tar.gz",
        "AgenticOS_1.8.3_amd64.AppImage",
        "AgenticOS_1.8.3_x64_en-US.msi",
        "AgenticOS_1.8.3_x64-setup.exe",
        "AgenticOS_1.8.3_amd64.deb",
        "AgenticOS-1.8.3-1.x86_64.rpm",
    ]
    assets = [
        {
            "name": name + suffix,
            "browser_download_url": f"https://github.com/vstorm-co/agenticos/releases/download/v1.8.3/{quote(name + suffix)}",
        }
        for name in names
        for suffix in ("", ".sig")
    ]
    for name in names:
        (tmp_path / (name + ".sig")).write_text("signature:" + name)
    if broken == "asset":
        assets.pop(0)
    elif broken == "signature-asset":
        assets.pop(1)
    elif broken == "signature-file":
        (tmp_path / (names[0] + ".sig")).unlink()
    elif broken == "empty":
        (tmp_path / (names[0] + ".sig")).write_text(" \n")
    elif broken == "duplicate":
        assets.append(assets[0])
    elif broken == "url":
        assets[0]["browser_download_url"] = "https://example.test/untrusted"
    release = {
        "tag_name": "v2.0.0" if broken == "version" else "v1.8.3",
        "published_at": "2026-11-02T12:00:00Z",
        "body": "Release notes",
        "draft": False,
        "prerelease": False,
        "assets": assets,
    }
    source = tmp_path / "release.json"
    source.write_text(json.dumps(release))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/desktop_updater_manifest.py"),
            str(source),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is (broken is None), result.stderr
    if broken is not None:
        assert not result.stdout, "partial manifest must never be published"
        return
    output = json.loads(result.stdout)
    assert output["version"] == "1.8.3"
    expected = {"darwin-aarch64", "darwin-x86_64", "linux-x86_64", "windows-x86_64"}
    assert expected <= output["platforms"].keys()
    assert len(output["platforms"]) == 11
    assert output["platforms"]["windows-x86_64"] == output["platforms"]["windows-x86_64-msi"]
    assert output["platforms"]["windows-x86_64-nsis"]["signature"] == "signature:" + names[4]
    for name, platform in zip(names[:4], expected_order(), strict=True):
        assert output["platforms"][platform]["signature"] == "signature:" + name
        assert (
            output["platforms"][platform]["url"]
            == assets[names.index(name) * 2]["browser_download_url"]
        )


def expected_order() -> tuple[str, ...]:
    return ("darwin-aarch64", "darwin-x86_64", "linux-x86_64", "windows-x86_64")
