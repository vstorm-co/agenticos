"""Validate the actual install archive, including both executable payloads."""

import json
import sys
import tarfile

with tarfile.open(sys.argv[1]) as bundle:
    root = "co.vstorm.agenticos"
    manifest_file = bundle.extractfile(f"{root}/plugin.json")
    assert manifest_file is not None
    manifest = json.load(manifest_file)
    assert manifest["id"] == root
    assert set(manifest["server"]["executables"]) == {"linux-amd64", "linux-arm64"}
    for platform, path in manifest["server"]["executables"].items():
        member = bundle.getmember(f"{root}/{path}")
        assert member.isfile() and member.mode & 0o111
        executable = bundle.extractfile(member)
        assert executable is not None
        header = executable.read(20)
        assert header[:4] == b"\x7fELF"
        assert int.from_bytes(header[18:20], "little") == (62 if platform == "linux-amd64" else 183)
    assert bundle.getmember(f"{root}/{manifest['icon_path']}").isfile()
sys.stdout.write(f"Verified {sys.argv[1]}: manifest, logo and two Linux ELF executables\n")
