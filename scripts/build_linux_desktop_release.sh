#!/usr/bin/env bash
set -euo pipefail

# tauri-action calls this from desktop/ with the build command and its arguments.
# Validate the final bundle before the action uploads installers or signatures.
bunx tauri "$@"
python3 ../scripts/check_desktop_installation.py \
  src-tauri/target/x86_64-unknown-linux-gnu/release/bundle --appimage-only
