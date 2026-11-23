"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { CaseKeyDraft } from "@/types/datasets";

/** How often a draft is asked about while its keys are listed. */
export const KEY_DRAFT_POLL_MS = 3000;

/**
 * The keys drafted from a case's reference answer, asked about again while they
 * are listed, and asking for or dismissing them.
 *
 * `enabled` is the caller's edit access: the routes answer 404 to anybody who may
 * not edit the dataset, so a reader never asks. A case with no draft is `null`;
 * `loading` and `error` say the answer is not known yet, so a draft that exists
 * is never replaced on the strength of a read that has not come back.
 */
export function useCaseKeyDraft(
  datasetId: string,
  caseId: string,
  { enabled }: { enabled: boolean },
) {
  const t = useTranslations("datasets.keyDraft");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const queryKey = qk.datasets.keyDraft(datasetId, caseId);
  const url = `/datasets/${datasetId}/cases/${caseId}/key-draft`;
  const { data, isLoading, error } = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        return await apiClient.get<CaseKeyDraft>(url);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? KEY_DRAFT_POLL_MS : false,
  });
  const start = useMutation({
    mutationFn: () => apiClient.post<CaseKeyDraft>(url),
    onSuccess: (draft) => queryClient.setQueryData(queryKey, draft),
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failedToStart"))),
  });
  const dismiss = useMutation({
    mutationFn: () => apiClient.delete(url),
    onSuccess: () => queryClient.setQueryData(queryKey, null),
    onError: (error) => toast.error(getErrorMessage(error, tErrors, t("failedToDismiss"))),
  });
  return {
    draft: data ?? null,
    loading: enabled && isLoading,
    error,
    start: () => start.mutate(),
    starting: start.isPending,
    dismiss: () => dismiss.mutate(),
  };
}
