"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/utils";
import { qk } from "@/lib/query-keys";
import type { AgentEnvironment, AgentEnvironmentList } from "@/types/agents";

/**
 * An agent's named environments - which published version answers under which
 * name. Promotion is an update that repoints `version_id`; there is no
 * unpinned state, so every mutation leaves each name answering with something
 * somebody chose.
 */
export function useAgentEnvironments(agentId: string | null) {
  const t = useTranslations("agents");
  const queryClient = useQueryClient();
  const base = `/agents/${agentId}/environments`;

  const { data, isLoading } = useQuery({
    queryKey: qk.environments.list(agentId ?? ""),
    queryFn: () => apiClient.get<AgentEnvironmentList>(base),
    enabled: agentId !== null,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: qk.environments.list(agentId ?? "") });

  const create = useMutation({
    mutationFn: (input: { name: string; version_id?: string }) =>
      apiClient.post<AgentEnvironment>(base, input),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, t("failedCreateEnvironment"))),
  });

  const promote = useMutation({
    mutationFn: ({ environmentId, versionId }: { environmentId: string; versionId: string }) =>
      apiClient.patch<AgentEnvironment>(`${base}/${environmentId}`, { version_id: versionId }),
    onSuccess: () => {
      invalidate();
      toast.success(t("promoted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, t("failedPromote"))),
  });

  const remove = useMutation({
    mutationFn: (environmentId: string) => apiClient.delete<void>(`${base}/${environmentId}`),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, t("failedRemoveEnvironment"))),
  });

  return {
    environments: data?.items ?? [],
    isLoading,
    create,
    promote,
    remove,
  };
}
