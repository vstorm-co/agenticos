import { apiClient } from "@/lib/api-client";

export type ProjectResourceKind = "agent" | "workflow" | "app" | "table";
export interface ProjectResourceRef {
  kind: ProjectResourceKind;
  resource_id: string;
}
export interface ProjectResource extends ProjectResourceRef {
  name: string;
  description: string | null;
  is_entrypoint: boolean;
  slug?: string | null;
  has_avatar?: boolean;
  avatar_color?: number | null;
}
export interface ProjectResources {
  items: ProjectResource[];
  total: number;
}
export interface ResourceCandidate {
  id: string;
  name: string;
  title?: string;
  description?: string | null;
  slug?: string | null;
  has_avatar?: boolean;
  avatar_color?: number | null;
}
const paths: Record<ProjectResourceKind, string> = {
  agent: "/agents",
  workflow: "/workflows",
  app: "/apps",
  table: "/tables",
};

export function listProjectResources(id: string, search = ""): Promise<ProjectResources> {
  return apiClient.get<ProjectResources>(`/projects/${id}/resources`, { params: { q: search } });
}
export function addProjectResources(
  id: string,
  resources: ProjectResourceRef[],
): Promise<ProjectResources> {
  return apiClient.post<ProjectResources>(`/projects/${id}/resources`, { resources });
}
export function removeProjectResource(id: string, ref: ProjectResourceRef): Promise<void> {
  return apiClient.delete<void>(`/projects/${id}/resources/${ref.kind}/${ref.resource_id}`);
}
export function setProjectEntrypoint(
  id: string,
  workflowId: string | null,
): Promise<ProjectResources> {
  return apiClient.patch<ProjectResources>(`/projects/${id}/entrypoint`, {
    workflow_id: workflowId,
  });
}
/** Complete authorized catalog, not a silently truncated first page. */
export async function projectResourceCandidates(
  kind: ProjectResourceKind,
): Promise<ResourceCandidate[]> {
  const items: ResourceCandidate[] = [];
  for (;;) {
    const page = await apiClient.get<{ items: ResourceCandidate[]; total: number }>(paths[kind], {
      params: { skip: String(items.length), limit: "100" },
    });
    items.push(
      ...page.items.map((item) => ({
        ...item,
        name: kind === "app" ? (item.title ?? item.name) : item.name,
      })),
    );
    if (!page.items.length || items.length >= page.total) return items;
  }
}
