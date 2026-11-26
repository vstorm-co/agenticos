#!/usr/bin/env bash
set -euo pipefail

# makepkg refuses root; the caller owns this disposable build/output directory.
ROOT="$(git rev-parse --show-toplevel)"
OUTPUT="$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "${1:?Usage: build_arch_package.sh OUTPUT_DIRECTORY}")"
mkdir -p "$OUTPUT"
VERSION="$(python -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/backend/pyproject.toml")"
git -C "$ROOT" archive --format=tar --prefix="agenticos-$VERSION/" HEAD | gzip -n > "$OUTPUT/agenticos-$VERSION.tar.gz"
SOURCE_SHA="$(sha256sum "$OUTPUT/agenticos-$VERSION.tar.gz" | cut -d ' ' -f 1)"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@SHA256@/$SOURCE_SHA/g" "$ROOT/packaging/arch/PKGBUILD.in" > "$OUTPUT/PKGBUILD"
cd "$OUTPUT"
makepkg --cleanbuild --noconfirm
makepkg --printsrcinfo > .SRCINFO
