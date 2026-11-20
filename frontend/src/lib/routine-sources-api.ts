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

export interface RoutineSourceReview {
  review_token: string;
  version_id: string;
  current: boolean;
  resources: string[];
  accounts: string[];
  unavailable_sources: string[];
  items?: RoutineSourceItem[];
}

const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/sources`;

export const routineSourcesApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineSourceReview>(path(agentId, triggerId)),
  replace: (agentId: string, triggerId: string, reviewToken: string) =>
    apiClient.put<RoutineSourceReview>(path(agentId, triggerId), { review_token: reviewToken }),
};
