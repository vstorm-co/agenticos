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

/** Headings whose sections speak to whoever runs the deployment, not to the people using it. */
const OPERATOR_HEADING =
  /^ {0,3}(#{1,6})[ \t]+(upgrading|notes for operators)(?:[ \t]+#+)?[ \t]*\r?$/i;
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]|\r?$)/;
const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;

/**
 * A release's notes without its operator sections - `Upgrading` and `Notes for
 * operators`, at whatever heading level the release uses. A section runs to the
 * next heading of its own level or above.
 */
export function memberReleaseNotes(body: string): string {
  const kept: string[] = [];
  let skipping: number | null = null;
  // A `#` comment in a shell block is not a heading, and an upgrade section is
  // where shell steps go. A block ends only at a fence of its own character, at
  // least as long and with nothing after it, as Markdown closes one.
  let fence: string | null = null;
  for (const line of body.split("\n")) {
    const heading = fence ? null : HEADING.exec(line);
    if (heading && skipping !== null && heading[1]!.length <= skipping) skipping = null;
    const operator = fence ? null : OPERATOR_HEADING.exec(line);
    if (skipping === null && operator) skipping = operator[1]!.length;
    const marker = FENCE.exec(line);
    if (marker && fence === null) fence = marker[1]!;
    else if (
      marker &&
      fence !== null &&
      marker[1]![0] === fence[0] &&
      marker[1]!.length >= fence.length &&
      !marker[2]!.trim()
    )
      fence = null;
    if (skipping === null) kept.push(line);
  }
  return kept.join("\n").trim();
}
