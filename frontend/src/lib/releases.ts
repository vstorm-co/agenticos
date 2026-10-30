export interface AppRelease {
  version: string;
  url: string;
}

export interface LatestReleaseResponse {
  latest: AppRelease | null;
}

interface Version {
  parts: [number, number, number];
  prerelease: boolean;
}

/** Stable release comparison also recognizes a running prerelease of the same version. */
export function parseVersion(value: string): Version | null {
  const match = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$/.exec(value);
  if (!match) return null;
  const major = match[1]!,
    minor = match[2]!,
    patch = match[3]!;
  if (
    [major, minor, patch].some(
      (part) => !/^(0|[1-9]\d*)$/.test(part) || !Number.isSafeInteger(Number(part)),
    )
  )
    return null;
  if (
    match[4]
      ?.split(".")
      .some((part) => !/^(0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)$/.test(part))
  )
    return null;
  if (match[5]?.split(".").some((part) => part.length === 0)) return null;
  return {
    parts: [Number(major), Number(minor), Number(patch)],
    prerelease: match[4] !== undefined,
  };
}

export function isNewerRelease(current: string, available: string): boolean {
  const running = parseVersion(current),
    latest = parseVersion(available);
  if (!running || !latest || latest.prerelease) return false;
  for (let index = 0; index < 3; index++) {
    if (latest.parts[index] !== running.parts[index])
      return latest.parts[index]! > running.parts[index]!;
  }
  return running.prerelease;
}

export interface ReleaseNotes extends AppRelease {
  body: string;
}
export interface CurrentReleaseResponse {
  release: ReleaseNotes | null;
}
