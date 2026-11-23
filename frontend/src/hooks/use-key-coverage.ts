"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { KeyCoverageReport } from "@/types/datasets";

/** How often a report is asked about while its keys are judged. */
export const KEY_COVERAGE_POLL_MS = 3000;

/**
 * An agent's coverage of a dataset's keys, asked about again while it is judged,
 * and asking for a new one.
 *
 * A pair with no report is `null`; one whose report could not be read has `error`,
 * so a refusal never reads as "not checked yet".
 */
export function useKeyCoverage(datasetId: string, agentId: string) {
  const t = useTranslations("datasets.keyCoverage");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const queryKey = qk.datasets.keyCoverage(datasetId, agentId);
  const url = `/datasets/${datasetId}/key-coverage`;
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        return await apiClient.get<KeyCoverageReport>(url, { params: { agent_id: agentId } });
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? KEY_COVERAGE_POLL_MS : false,
  });
  const start = useMutation({
    mutationFn: () => apiClient.post<KeyCoverageReport>(url, { agent_id: agentId }),
    onSuccess: (report) => queryClient.setQueryData(queryKey, report),
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failedToStart"))),
  });
  return {
    report: data ?? null,
    loading: isLoading,
    error,
    start: () => start.mutate(),
    starting: start.isPending,
  };
}
