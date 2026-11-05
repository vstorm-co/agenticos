import { apiClient } from "@/lib/api-client";

export interface ProjectTracking {
  id: string;
  project_id: string;
  agent_id: string;
  agent_version_id: string;
  table_id: string;
  trigger_id: string;
  conversation_id: string | null;
}
export interface ProjectTrackingReview {
  review_token: string;
  base_agent_id: string;
  base_version_id: string;
  base_agent_name: string;
  resources: string[];
  accounts: string[];
  unavailable_sources: string[];
}
export interface ProjectTrackingCreate {
  base_agent_id: string;
  base_version_id: string;
  source_review_token: string;
  publish_and_start: true;
  agent_name: string;
  table_name: string;
  table_visibility: "private";
  interval_seconds: number;
}
const path = (projectId: string) => `/projects/${projectId}/tracking`;
export const projectTrackingApi = {
  get: (projectId: string) => apiClient.get<ProjectTracking | null>(path(projectId)),
  review: (projectId: string, agentId: string, versionId: string) =>
    apiClient.get<ProjectTrackingReview>(`${path(projectId)}/review`, {
      params: { base_agent_id: agentId, base_version_id: versionId },
    }),
  create: (projectId: string, data: ProjectTrackingCreate) =>
    apiClient.post<ProjectTracking>(path(projectId), data),
};
