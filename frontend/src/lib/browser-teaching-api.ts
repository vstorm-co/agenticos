/**
 * API client for reviewing a Teach a task recording (#113).
 *
 * A session holds structural steps only - an origin, an action and a control's
 * role. The review adds the reviewer's own labels and parameter names; nothing
 * typed or shown during the demonstration is ever sent back here.
 */

import { apiClient } from "./api-client";

export type TeachingStatus =
  "recording" | "paused" | "review" | "proposing" | "proposed" | "discarded" | "expired";

export type TeachingAction =
  "navigate" | "click" | "select" | "input_parameter" | "scroll" | "checkpoint";

export interface TeachingStep {
  sequence: number;
  action: TeachingAction;
  origin: string;
  target: { role: string; fingerprint: string } | null;
  direction: "up" | "down" | null;
  human_step: boolean;
}

export interface ReviewedStep {
  sequence: number;
  label: string | null;
  parameter: string | null;
}

export interface BrowserTeaching {
  id: string;
  agent_id: string;
  run_id: string;
  title: string;
  allowed_origins: string[];
  status: TeachingStatus;
  revision: number;
  reason_code: string | null;
  events: TeachingStep[];
  review: ReviewedStep[];
  parameters: string[];
  proposal_name: string | null;
  proposal_id: string | null;
  expires_at: string;
}

const ROOT = "/browser-teachings";

/** A revision travels in `If-Match`, so a stale edit is refused rather than applied. */
const revisionHeader = (revision: number) => ({ headers: { "If-Match": String(revision) } });

export async function getBrowserTeaching(id: string): Promise<BrowserTeaching> {
  return apiClient.get<BrowserTeaching>(`${ROOT}/${id}`);
}

export async function reviewBrowserTeaching(
  id: string,
  revision: number,
  steps: ReviewedStep[],
): Promise<BrowserTeaching> {
  return apiClient.patch<BrowserTeaching>(
    `${ROOT}/${id}`,
    { action: "review", steps },
    revisionHeader(revision),
  );
}

export async function proposeBrowserTeaching(
  id: string,
  revision: number,
  name: string,
): Promise<BrowserTeaching> {
  return apiClient.post<BrowserTeaching>(
    `${ROOT}/${id}/propose`,
    { name },
    revisionHeader(revision),
  );
}
