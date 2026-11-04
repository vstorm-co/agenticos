/**
 * What the platform proposed to the signed-in person, and their answers (#2301).
 *
 * Proposals are made in the background, overnight; the console only reads them
 * and records what the person decided.
 */

import { apiClient } from "./api-client";

export type SuggestionKind = "routine" | "agent" | "profile" | "role_pack" | "finding";
export type SuggestionStatus = "open" | "accepted" | "dismissed";

export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  status: SuggestionStatus;
  title: string;
  detail: string | null;
  /**
   * What accepting it needs: `prompt` and `cron` for a routine, `request` for an
   * agent, the profile fields for a profile, `pack` for a role pack. A finding
   * carries `server` (a catalog key or null), `account` and `url`, each maybe null.
   */
  payload: Record<string, unknown>;
  /** The watch a finding came from. */
  watch_id?: string | null;
  /** A finding sent at once rather than kept for the briefing. */
  urgent?: boolean;
  created_at: string;
}

interface SuggestionList {
  items: Suggestion[];
  total: number;
}

export async function listSuggestions(): Promise<Suggestion[]> {
  return (await apiClient.get<SuggestionList>("/me/suggestions")).items;
}

/** Every proposal the person was made here, answered or not, newest first. */
export async function listSuggestionHistory(): Promise<Suggestion[]> {
  return (await apiClient.get<SuggestionList>("/me/suggestions?decided=true")).items;
}

/** The first messages written for the person in the active organization, none until written. */
export async function listPersonalStarters(): Promise<string[]> {
  return (await apiClient.get<{ items: string[] }>("/me/suggestions/starters")).items;
}

/** Bring back one the person dismissed, to answer again. */
export async function restoreSuggestion(id: string): Promise<Suggestion> {
  return apiClient.post<Suggestion>(`/me/suggestions/${id}/restore`);
}

export async function acceptSuggestion(id: string): Promise<Suggestion> {
  return apiClient.post<Suggestion>(`/me/suggestions/${id}/accept`);
}

export async function dismissSuggestion(id: string): Promise<Suggestion> {
  return apiClient.post<Suggestion>(`/me/suggestions/${id}/dismiss`);
}
