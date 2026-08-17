/**
 * API client for a person's named dashboard presets.
 *
 * A preset is a saved arrangement kept under a name; applying one is not a call
 * here but a `putLayout` with the preset's entries (see `dashboard-layout-api`),
 * so the active arrangement keeps a single write path. Like the layout, presets
 * are per user and per organization, and the active organization travels on the
 * header `apiClient` already attaches — these calls carry no org id of their own.
 */

import { apiClient } from "./api-client";
import type { StoredEntry } from "./dashboard/preference";

export interface DashboardPreset {
  id: string;
  name: string;
  entries: StoredEntry[];
}

interface PresetList {
  items: DashboardPreset[];
  total: number;
}

const ROOT = "/me/dashboard-layout/presets";

export async function listPresets(): Promise<DashboardPreset[]> {
  const list = await apiClient.get<PresetList>(ROOT);
  return list.items;
}

export async function createPreset(name: string, entries: StoredEntry[]): Promise<DashboardPreset> {
  return apiClient.post<DashboardPreset>(ROOT, { name, entries });
}

export async function deletePreset(presetId: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${presetId}`);
}
