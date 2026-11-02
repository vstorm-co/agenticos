import { apiClient } from "@/lib/api-client";

export interface RoutineActionKey {
  capability_id: string;
  tool_id: string;
}
export interface RoutineActionOption extends RoutineActionKey {
  name: string;
  consented: boolean;
  waivable: boolean;
}
export interface RoutineActionOptions {
  can_waive: boolean;
  review_token: string;
  items: RoutineActionOption[];
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
