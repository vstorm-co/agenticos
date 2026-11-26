import { apiClient } from "./api-client";

export interface ShippedAgentUpdate {
  revision: string;
  changes: { version: "draft" | "published"; field: string; before: string; after: string }[];
}

export function readShippedAgentUpdate(agentId: string) {
  return apiClient.get<ShippedAgentUpdate>(`/agents/${agentId}/shipped-update`);
}

export function applyShippedAgentUpdate(agentId: string, revision: string) {
  return apiClient.post<null>(`/agents/${agentId}/shipped-update`, { expected_revision: revision });
}
