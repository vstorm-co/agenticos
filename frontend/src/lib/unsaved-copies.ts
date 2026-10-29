/**
 * Copies of unsaved edits kept in this browser, so leaving a page without
 * saving does not lose the work.
 *
 * Nothing here reaches the server: a copy is what a person typed, read back
 * only into the place they typed it. Storage can be full, disabled or blocked
 * outright, and a copy is a convenience, so every access fails quietly.
 */

const PREFIX = "agenticos.unsaved.";

/** Beyond this a copy is not kept at all, rather than kept in part. */
export const COPY_LIMIT = 64 * 1024;

/** One kept edit, and the version of what it edits it was made on. */
export interface UnsavedCopy<T = unknown> {
  key: string;
  /** Which edit in the dataset: `grading`, `case:new` or `case:<id>`. */
  place: string;
  base: number;
  savedAt: string;
  value: T;
}

/** Where the copy of one edit lives: per organization, dataset and place. */
export function copyKey(organizationId: string, datasetId: string, place: string): string {
  return `${PREFIX}${organizationId}:${datasetId}:${place}`;
}

export function writeCopy(key: string, base: number, value: unknown): void {
  try {
    const stored = JSON.stringify({ base, savedAt: new Date().toISOString(), value });
    if (stored.length > COPY_LIMIT) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, stored);
  } catch {
    // Kept or not, the edit itself is on screen; only the backup is missing.
  }
}

export function removeCopy(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Nothing kept can be read either, so nothing is offered back.
  }
}

/** Every copy kept for one dataset, oldest first. */
export function readCopies(organizationId: string, datasetId: string): UnsavedCopy[] {
  const scope = copyKey(organizationId, datasetId, "");
  const copies: UnsavedCopy[] = [];
  try {
    for (let index = 0; index < window.localStorage.length; index++) {
      const key = window.localStorage.key(index);
      if (!key?.startsWith(scope)) continue;
      try {
        const { base, savedAt, value } = JSON.parse(String(window.localStorage.getItem(key)));
        if (typeof base !== "number" || typeof savedAt !== "string") continue;
        copies.push({ key, place: key.slice(scope.length), base, savedAt, value });
      } catch {
        continue;
      }
    }
  } catch {
    return [];
  }
  return copies.sort((a, b) => a.savedAt.localeCompare(b.savedAt));
}

/** Forget every kept edit: they belong to the account and organization being left. */
export function clearCopies(): void {
  try {
    const keys: string[] = [];
    for (let index = 0; index < window.localStorage.length; index++) {
      const key = window.localStorage.key(index);
      if (key?.startsWith(PREFIX)) keys.push(key);
    }
    for (const key of keys) window.localStorage.removeItem(key);
  } catch {
    // Storage that cannot be read holds nothing this could have offered.
  }
}
