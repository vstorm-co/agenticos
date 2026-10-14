/**
 * API client for the sign-ins a person kept from their own browses (#2129).
 *
 * Read, forget, and open a browser to sign in with: a sign-in is kept only by
 * its owner handing a browser back with "keep me signed in" ticked - one they
 * took over from an agent, or one opened here - and no route returns what one
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

/** Where an opened sign-in browser is watched and driven: its live view. */
export interface SignInSession {
  run_id: string;
  call_id: string;
}

/** Whether this deployment names a browser to sign in with from Settings. */
export function getSignInBrowser(): Promise<{ available: boolean }> {
  return apiClient.get<{ available: boolean }>("/browser-sign-ins/browser");
}

/** Open a browser on `url`, held by the caller from the start. */
export function startSignIn(url: string): Promise<SignInSession> {
  return apiClient.post<SignInSession>("/browser-sign-ins/sessions", { url });
}
