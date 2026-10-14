/**
 * API client for the sign-ins a person kept from their own browses (#2129).
 *
 * Read and forget, nothing else: a sign-in is kept only by its owner handing the
 * browser back with "keep me signed in" ticked, and no route returns what one
 * holds.
 */

import { apiClient } from "./api-client";

export interface BrowserSignIn {
  id: string;
  /** The host signed in to, without `www.`. */
  site: string;
  created_at: string | null;
  updated_at: string | null;
  /** When a browse last started signed in with it. */
  last_used_at: string | null;
}

export interface BrowserSignInList {
  items: BrowserSignIn[];
  total: number;
}

export function getMySignIns(): Promise<BrowserSignInList> {
  return apiClient.get<BrowserSignInList>("/browser-sign-ins");
}

export function forgetSignIn(id: string): Promise<void> {
  return apiClient.delete<void>(`/browser-sign-ins/${id}`);
}
