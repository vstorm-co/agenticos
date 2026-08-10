/**
 * API client for a person's saved dashboard arrangement.
 *
 * The layout is per user and per organization; the active organization travels
 * on the header `apiClient` already attaches, so these calls carry no org id of
 * their own. A 404 from GET is not an error here - it is the signal that the
 * person has saved nothing and the audience default should stand - so it is
 * turned into `null` rather than thrown.
 */

import { ApiError, apiClient } from "./api-client";
import type { StoredEntry } from "./dashboard/preference";

export interface StoredLayout {
  entries: StoredEntry[];
}

const ROOT = "/me/dashboard-layout";

export async function getLayout(): Promise<StoredLayout | null> {
  try {
    return await apiClient.get<StoredLayout>(ROOT);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function putLayout(entries: StoredEntry[]): Promise<StoredLayout> {
  return apiClient.put<StoredLayout>(ROOT, { entries });
}

export async function deleteLayout(): Promise<void> {
  await apiClient.delete(ROOT);
}
