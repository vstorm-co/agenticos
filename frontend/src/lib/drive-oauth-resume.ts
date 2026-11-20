/**
 * Keeping the sync-source wizard alive across a Google consent.
 *
 * Connecting an account leaves the page for the provider and comes back to the
 * same path, which remounts it with the wizard closed. What the reader had
 * filled in is written here before the browser leaves, and the wizard reads it
 * back on mount and reopens on the credential step, with the account that
 * appeared since as the one chosen.
 *
 * `sessionStorage`, like `oauth-return`: the trip starts and ends in this tab.
 * Ten minutes is the lifetime of the OAuth return cookie; a snapshot older than
 * that belongs to a consent nobody is coming back from.
 */
import type { SyncSourceCreate } from "@/lib/rag-api";

const KEY = "syncSourceDriveResume";
const MAX_AGE_MS = 10 * 60 * 1000;

export interface DriveResume {
  form: SyncSourceCreate;
  /** The Drive-capable accounts the organization held before the consent. */
  knownAccountIds: string[];
  savedAt: number;
}

export function saveDriveResume(
  form: SyncSourceCreate,
  knownAccountIds: string[],
  now: number = Date.now(),
): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ form, knownAccountIds, savedAt: now }));
  } catch {
    // A browser that refuses site data still gets the consent; the cost is
    // starting the wizard over when it comes back.
  }
}

/**
 * The snapshot, if one is fresh and readable. Null otherwise, and on the server,
 * where there is no storage. It stays in place: `clearDriveResume` forgets it
 * once the wizard has taken it.
 */
export function readDriveResume(now: number = Date.now()): DriveResume | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  return isDriveResume(parsed) && now - parsed.savedAt <= MAX_AGE_MS ? parsed : null;
}

function isDriveResume(value: unknown): value is DriveResume {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const form = v.form as Record<string, unknown> | null | undefined;
  return (
    typeof form === "object" &&
    form !== null &&
    typeof form.name === "string" &&
    typeof form.connector_type === "string" &&
    typeof form.config === "object" &&
    form.config !== null &&
    Array.isArray(v.knownAccountIds) &&
    v.knownAccountIds.every((id) => typeof id === "string") &&
    typeof v.savedAt === "number"
  );
}

/** Forget the snapshot, once it has been read into the wizard. */
export function clearDriveResume(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // Nothing stored to forget.
  }
}
