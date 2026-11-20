"""Freeze Python's column-label casefold for browsers, independent of their Unicode version.

Run with the pinned backend interpreter after changing the server's Unicode data:
    uv run --directory backend python ../scripts/gen_column_label_casefold.py
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

TARGET = (
    Path(__file__).resolve().parents[1] / "frontend/src/lib/workflows/column-label-casefold.json"
)


def main() -> int:
    """Write the sparse full-fold table, or verify the committed copy."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if unicodedata.unidata_version != "17.0.0":
        parser.error("Use the pinned backend Python (Unicode 17.0.0)")
    folds = {
        chr(code): chr(code).casefold()
        for code in range(sys.maxunicode + 1)
        if chr(code).casefold() != chr(code)
    }
    content = json.dumps(folds, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if TARGET.read_text() != content:
            print("Column-label casefold data is stale", file=sys.stderr)
            return 1
    else:
        TARGET.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
