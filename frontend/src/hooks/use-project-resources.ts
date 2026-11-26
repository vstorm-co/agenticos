"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addProjectResources,
  listProjectResources,
  projectResourceCandidates,
  removeProjectResource,
  setProjectEntrypoint,
  type ProjectResourceKind,
  type ProjectResourceRef,
} from "@/lib/project-resources-api";
import { qk } from "@/lib/query-keys";

export function useProjectResources(id: string, search = "") {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: qk.projects.resources(id, search),
    queryFn: () => listProjectResources(id, search),
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: qk.projects.detail(id) }),
      client.invalidateQueries({ queryKey: qk.agents.all() }),
      client.invalidateQueries({ queryKey: qk.workflows.all() }),
    ]);
  };
  const add = useMutation({
    mutationFn: (refs: ProjectResourceRef[]) => addProjectResources(id, refs),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (ref: ProjectResourceRef) => removeProjectResource(id, ref),
    onSuccess: refresh,
  });
  const entrypoint = useMutation({
    mutationFn: (workflowId: string | null) => setProjectEntrypoint(id, workflowId),
    onSuccess: refresh,
  });
  return { ...query, add, remove, entrypoint };
}
export function useProjectResourceCandidates(kind: ProjectResourceKind, enabled: boolean) {
  return useQuery({
    queryKey: qk.projects.candidates(kind),
    queryFn: () => projectResourceCandidates(kind),
    enabled,
  });
}
