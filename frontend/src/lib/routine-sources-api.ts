import { apiClient } from "@/lib/api-client";

export type RoutineSourceKind =
  | "capability"
  | "skill"
  | "context"
  | "knowledge"
  | "table"
  | "delegate"
  | "remote_agent"
  | "platform"
  | "mcp_account"
  | "chat_connection"
  | "phone"
  | "terminal_account"
  | "terminal_credential"
  | "event_source";

/** One reviewed source, named; `name` is null for one that is gone or not visible. */
export interface RoutineSourceItem {
  kind: RoutineSourceKind;
  id?: string | null;
  name?: string | null;
  detail?: string | null;
}

export type RoutineSourceMode = "follow_agent" | "restricted";

export interface RoutineSourceConsent {
  review_token: string;
  mode?: RoutineSourceMode;
}

export interface RoutineSourceReview {
  /** Older cached responses represent a restricted reviewed snapshot. */
  mode?: RoutineSourceMode;
  review_token: string;
  version_id: string;
  current: boolean;
  resources: string[];
  accounts: string[];
  unavailable_sources: string[];
  /** Absent in older responses, where every unavailable source must block saving. */
  required_unavailable_sources?: string[];
  items?: RoutineSourceItem[];
}

const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/sources`;

export const routineSourcesApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineSourceReview>(path(agentId, triggerId)),
  replace: (agentId: string, triggerId: string, consent: RoutineSourceConsent) =>
    apiClient.put<RoutineSourceReview>(path(agentId, triggerId), consent),
};

/** Missing classifications fail closed; only explicit optional gaps can be inherited. */
export function routineSourceBlockers(
  review: RoutineSourceReview,
  mode: RoutineSourceMode,
): readonly string[] {
  return mode === "restricted"
    ? review.unavailable_sources
    : (review.required_unavailable_sources ?? review.unavailable_sources);
}
