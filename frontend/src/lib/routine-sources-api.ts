import { apiClient } from "@/lib/api-client";

export interface RoutineSourceReview {
  review_token: string;
  version_id: string;
  current: boolean;
  resources: string[];
  accounts: string[];
  unavailable_sources: string[];
}

const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/sources`;

export const routineSourcesApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineSourceReview>(path(agentId, triggerId)),
  replace: (agentId: string, triggerId: string, reviewToken: string) =>
    apiClient.put<RoutineSourceReview>(path(agentId, triggerId), { review_token: reviewToken }),
};
