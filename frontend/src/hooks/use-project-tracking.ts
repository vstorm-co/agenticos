"use client";

import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { projectTrackingApi, type ProjectTrackingCreate } from "@/lib/project-tracking-api";
import { qk } from "@/lib/query-keys";

export function useProjectTracking(projectId: string) {
  const client = useQueryClient();
  const t = useTranslations("errors");
  const query = useQuery({
    queryKey: qk.projects.tracking(projectId),
    queryFn: () => projectTrackingApi.get(projectId),
  });
  const create = useMutation({
    mutationFn: (data: ProjectTrackingCreate) => projectTrackingApi.create(projectId, data),
    onSuccess: (data) => {
      client.setQueryData(qk.projects.tracking(projectId), data);
      void client.invalidateQueries({ queryKey: qk.projects.detail(projectId), exact: true });
      void client.invalidateQueries({ queryKey: qk.triggers.all() });
      void client.invalidateQueries({ queryKey: qk.agents.all() });
      void client.invalidateQueries({ queryKey: qk.tables.all() });
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, t));
      void client.invalidateQueries({ queryKey: qk.projects.tracking(projectId) });
      void client.invalidateQueries({ queryKey: qk.projects.trackingReviews(projectId) });
    },
  });
  return { ...query, create };
}

export function useProjectTrackingReview(
  projectId: string,
  agentId: string | null,
  versionId: string | null,
) {
  return useQuery({
    queryKey: qk.projects.trackingReview(projectId, agentId, versionId),
    queryFn:
      agentId === null || versionId === null
        ? skipToken
        : () => projectTrackingApi.review(projectId, agentId, versionId),
  });
}
