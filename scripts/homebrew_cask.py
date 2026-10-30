"""Generate a cask from the exact DMGs attached to a platform release."""

import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import quote


def cask(folder: Path, tag: str) -> str:
    if re.fullmatch(r"v1\.\d+\.\d+", tag) is None:
        raise ValueError("Expected a stable platform release tag")
    files: dict[str, Path] = {}
    for arch in ("aarch64", "x64"):
        candidates = list(folder.glob(f"*_{arch}.dmg"))
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one {arch} DMG")
        files[arch] = candidates[0]
    hashes: dict[str, str] = {}
    for arch, path in files.items():
        with path.open("rb") as stream:
            hashes[arch] = hashlib.file_digest(stream, "sha256").hexdigest()
    return f'''cask "agenticos" do
  version "{tag[1:]}"
  on_arm do
    sha256 "{hashes["aarch64"]}"
    url "https://github.com/vstorm-co/agenticos/releases/download/{tag}/{quote(files["aarch64"].name)}"
  end
  on_intel do
    sha256 "{hashes["x64"]}"
    url "https://github.com/vstorm-co/agenticos/releases/download/{tag}/{quote(files["x64"].name)}"
  end
  name "AgenticOS"
  desc "Build, run and govern your company's AI agents"
  homepage "https://github.com/vstorm-co/agenticos"
  app "AgenticOS.app"
end
'''


if __name__ == "__main__":
    print(cask(Path(sys.argv[1]), sys.argv[2]), end="")
