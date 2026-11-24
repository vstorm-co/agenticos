#!/usr/bin/env bash
# Install the pinned, checksummed ffmpeg/ffprobe build the media-inspection tests
# run, and put it on the runner's PATH. `ffprobe` inspects; `ffmpeg` builds the
# synthetic MP4 the decode test feeds it. CI only: a laptop installs ffmpeg itself.
set -euo pipefail
test "$(uname -m)" = x86_64
probe_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/ffprobe.XXXXXX")"
package='ffmpeg-n9.0.2-39-g7adfbe40dc-linux64-lgpl-9.0'
archive="$probe_dir/archive.tar.xz"
timeout 180s curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' \
  --connect-timeout 10 --max-time 60 \
  --retry 2 --retry-delay 2 --retry-max-time 150 \
  --output "$archive" \
  "https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/$package.tar.xz"
printf '%s  %s\n' '6046d6731b26f58887e953561551d254a6eec9fbca4100dfeab56e19af8328d5' "$archive" | sha256sum --check --strict
timeout 60s tar -xJf "$archive" -C "$probe_dir" --no-same-owner --no-same-permissions \
  "$package/bin/ffprobe" "$package/bin/ffmpeg" "$package/LICENSE.txt"
timeout 10s "$probe_dir/$package/bin/ffprobe" -version
timeout 10s "$probe_dir/$package/bin/ffmpeg" -version
printf '%s\n' "$probe_dir/$package/bin" >> "$GITHUB_PATH"
