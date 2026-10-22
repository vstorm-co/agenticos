/**
 * What the platform proposed to the signed-in person, and their answers (#2301).
 *
 * Proposals are made in the background, overnight; the console only reads them
 * and records what the person decided.
 */

import { apiClient } from "./api-client";

export type SuggestionKind = "routine" | "agent" | "profile" | "role_pack";

export interface Suggestion {
  id: string;
  kind: SuggestionKind;
  title: string;
  detail: string | null;
  /**
   * What accepting it needs: `prompt` and `cron` for a routine, `request` for an
   * agent, the profile fields for a profile, `pack` for a role pack.
   */
  payload: Record<string, unknown>;
  created_at: string;
}

interface SuggestionList {
  items: Suggestion[];
  total: number;
}

export async function listSuggestions(): Promise<Suggestion[]> {
  return (await apiClient.get<SuggestionList>("/me/suggestions")).items;
}

export async function acceptSuggestion(id: string): Promise<Suggestion> {
  return apiClient.post<Suggestion>(`/me/suggestions/${id}/accept`);
}

export async function dismissSuggestion(id: string): Promise<Suggestion> {
  return apiClient.post<Suggestion>(`/me/suggestions/${id}/dismiss`);
}
