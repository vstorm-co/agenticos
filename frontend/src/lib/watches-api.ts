/**
 * What the signed-in person watches in their own connections (#2301).
 *
 * A watch is the proactive look pointed at one of their accounts: read on a
 * cadence they choose, with what is new arriving as a finding.
 */

import { apiClient } from "./api-client";

/** Why a watch that is on is not being read. */
export type WatchStopped = "watches_off" | "connection_disabled";

export interface Watch {
  id: string;
  connection_id: string;
  connection_name: string;
  /** Its server's catalog key; `null` for a custom server. */
  server: string | null;
  preset_key: string | null;
  title: string;
  instructions: string;
  exclusions: string[];
  urgent: boolean;
  interval_minutes: number;
  is_active: boolean;
  stopped: WatchStopped | null;
  next_run_at: string;
  last_run_at: string | null;
  /** Its findings still open in the person's inbox. */
  waiting: number;
  created_at: string;
}

export interface WatchPreset {
  key: string;
  server: string;
  instructions: string;
  interval_minutes: number;
  urgent: boolean;
}

export interface WatchDraft {
  connection_id: string;
  preset_key: string | null;
  title: string;
  instructions: string;
  urgent: boolean;
  interval_minutes: number;
}

export type WatchChanges = Partial<
  Pick<Watch, "title" | "instructions" | "urgent" | "interval_minutes" | "is_active" | "exclusions">
>;

interface Listed<T> {
  items: T[];
  total: number;
}

export async function listWatches(): Promise<Watch[]> {
  return (await apiClient.get<Listed<Watch>>("/me/watches")).items;
}

export async function listWatchPresets(): Promise<WatchPreset[]> {
  return (await apiClient.get<Listed<WatchPreset>>("/me/watches/presets")).items;
}

export async function createWatch(draft: WatchDraft): Promise<Watch> {
  return apiClient.post<Watch>("/me/watches", draft);
}

export async function updateWatch(id: string, changes: WatchChanges): Promise<Watch> {
  return apiClient.patch<Watch>(`/me/watches/${id}`, changes);
}

export async function deleteWatch(id: string): Promise<void> {
  await apiClient.delete<void>(`/me/watches/${id}`);
}
