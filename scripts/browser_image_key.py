#!/usr/bin/env python3
"""Browser reuse key: complete context, pinned base, weekly package refresh."""

import argparse
import hashlib
import re
import subprocess
from datetime import UTC, datetime


def cache_key(tree: str, base_digest: str, week: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ValueError("Invalid context tree")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", base_digest):
        raise ValueError("Invalid base manifest digest")
    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise ValueError("Invalid refresh week")
    return "input-" + hashlib.sha256(f"{tree}\n{base_digest}\n{week}".encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sha")
    parser.add_argument("digest")
    args = parser.parse_args()
    tree = subprocess.check_output(
        ["git", "rev-parse", f"{args.sha}:docker/browser"], text=True, timeout=30
    ).strip()
    print(cache_key(tree, args.digest, datetime.now(UTC).strftime("%G-W%V")))


if __name__ == "__main__":
    main()
