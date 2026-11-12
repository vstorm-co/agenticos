import { apiClient } from "@/lib/api-client";

export interface CapabilityActionKey {
  capability_id: string;
  tool_id: string;
}
export interface McpActionKey {
  connection_id: string;
  authorization_generation: string;
  endpoint_hash: string;
  tool_id: string;
}
export type RoutineActionKey = CapabilityActionKey | McpActionKey;
interface ActionReview {
  name: string;
  consented: boolean;
  previously_consented?: boolean;
  waivable: boolean;
}
export type RoutineActionOption =
  | (CapabilityActionKey & ActionReview)
  | (McpActionKey &
      ActionReview & {
        account_name: string;
        account_scope: "personal" | "organization";
      });
export function routineActionKey(action: RoutineActionOption): RoutineActionKey {
  if ("capability_id" in action) {
    return { capability_id: action.capability_id, tool_id: action.tool_id };
  }
  return {
    connection_id: action.connection_id,
    authorization_generation: action.authorization_generation,
    endpoint_hash: action.endpoint_hash,
    tool_id: action.tool_id,
  };
}
export function routineActionIdentity(action: RoutineActionOption): string {
  return JSON.stringify(routineActionKey(action));
}
export interface RoutineActionOptions {
  max_actions?: number;
  review_changes?: ("version" | "intent" | "instructions" | "actions")[];
  can_waive: boolean;
  review_token: string;
  items: RoutineActionOption[];
  unavailable_sources?: string[];
}
const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/action-consents`;
export const routineActionsApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineActionOptions>(path(agentId, triggerId)),
  replace: (
    agentId: string,
    triggerId: string,
    actions: RoutineActionKey[],
    reviewToken?: string,
  ) =>
    apiClient.put<RoutineActionOptions>(path(agentId, triggerId), {
      actions,
      review_token: reviewToken,
    }),
};
