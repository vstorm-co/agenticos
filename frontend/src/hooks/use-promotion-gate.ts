"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { PromotionGate, PromotionGateRun } from "@/types/promotion-gate";

/**
 * Whether a version may be promoted onto an environment, guard by guard.
 *
 * Read only for an environment that names guards; an unguarded one takes any
 * version, so there is nothing to ask.
 */
export function usePromotionGate(
  agentId: string,
  environmentId: string,
  versionId: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.evalSuites.gate(agentId, environmentId, versionId),
    queryFn: () =>
      apiClient.get<PromotionGate>(`/agents/${agentId}/environments/${environmentId}/gate`, {
        params: { version_id: versionId },
      }),
    enabled,
  });
  return { gate: data, isLoading, error, refetch };
}

/** Run an environment's guards that have not passed on a version, as the caller. */
export function useRunPromotionGate(agentId: string) {
  const t = useTranslations("agents");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ environmentId, versionId }: { environmentId: string; versionId: string }) =>
      apiClient.post<PromotionGateRun>(
        `/agents/${agentId}/environments/${environmentId}/gate/run`,
        {
          version_id: versionId,
        },
      ),
    onSuccess: (run, { environmentId, versionId }) => {
      queryClient.setQueryData(qk.evalSuites.gate(agentId, environmentId, versionId), run.gate);
      void queryClient.invalidateQueries({ queryKey: qk.evalSuites.forAgent(agentId) });
      toast.success(t("guardsStarted", { count: run.started.length }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failedGuardsRun"))),
  });
}
