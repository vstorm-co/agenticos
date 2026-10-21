"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PAGE_SIZE } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  CaseGeneration,
  CaseGenerationEstimate,
  CaseGenerationList,
  CaseGenerationRequest,
  CaseProposalList,
} from "@/types/case-generation";
import type { DatasetCaseContent, DatasetVersion } from "@/types/datasets";

/** How often a running generation is asked about while it runs. */
export const GENERATION_POLL_MS = 3000;

/** One drafted case to accept - as drafted, or as the reviewer edited it. */
export interface Decision {
  id: string;
  content?: DatasetCaseContent;
}

/**
 * The dataset's newest generations, asked about again while one is running.
 *
 * `enabled` is the caller's edit access: the routes answer 404 to anybody who
 * may not edit the dataset, so a reader never asks.
 */
export function useCaseGenerations(datasetId: string, { enabled }: { enabled: boolean }) {
  const { data, error } = useQuery({
    queryKey: qk.datasets.generations(datasetId),
    queryFn: () => apiClient.get<CaseGenerationList>(`/datasets/${datasetId}/generations`),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.items.some((generation) => generation.status === "running")
        ? GENERATION_POLL_MS
        : false,
  });
  return { generations: data?.items ?? [], error };
}

/**
 * A page of the drafted cases waiting on a dataset, and deciding them.
 *
 * Every decision invalidates the whole dataset: an Accept is a new version, and
 * both change how many drafts wait.
 */
export function useCaseProposals(
  datasetId: string,
  { enabled, skip = 0, limit = PAGE_SIZE }: { enabled: boolean; skip?: number; limit?: number },
) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.datasets.proposals(datasetId, { skip, limit }),
    queryFn: () =>
      apiClient.get<CaseProposalList>(`/datasets/${datasetId}/proposals`, {
        params: { skip: String(skip), limit: String(limit) },
      }),
    enabled,
    placeholderData: (previous) => previous,
  });

  const changed = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
    [queryClient],
  );

  // Without `onError` on accept: an edited draft is refused in the dialog still on
  // screen, which owns where to say it. A one-click Accept says it in a toast.
  const accept = useMutation({
    mutationFn: (items: Decision[]) =>
      apiClient.post<DatasetVersion>(`/datasets/${datasetId}/proposals/accept`, { items }),
    onSuccess: async (version) => {
      await changed();
      toast.success(
        t("proposalsAccepted", { count: version.changed_cases, version: version.number }),
      );
    },
  });

  const dismiss = useMutation({
    mutationFn: (ids: string[]) =>
      apiClient.post<void>(`/datasets/${datasetId}/proposals/dismiss`, { ids }),
    onSuccess: async (_, ids) => {
      await changed();
      toast.success(t("proposalsDismissed", { count: ids.length }));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });

  return {
    proposals: data?.items ?? [],
    total: data?.total ?? 0,
    hidden: data?.hidden ?? 0,
    isLoading,
    error,
    refetch,
    accept,
    dismiss,
    isDeciding: accept.isPending || dismiss.isPending,
  };
}

/** Estimating a generation, then starting it. Neither says anything on its own: the dialog does. */
export function useGenerateCases(datasetId: string) {
  const queryClient = useQueryClient();
  const estimate = useMutation({
    mutationFn: (request: CaseGenerationRequest) =>
      apiClient.post<CaseGenerationEstimate>(
        `/datasets/${datasetId}/generations/estimate`,
        request,
      ),
  });
  const start = useMutation({
    mutationFn: (request: CaseGenerationRequest) =>
      apiClient.post<CaseGeneration>(`/datasets/${datasetId}/generations`, request),
    // The first generation seeds the generator, which the panel then links to.
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.datasets.generations(datasetId) }),
        queryClient.invalidateQueries({ queryKey: qk.agents.generators() }),
      ]),
  });
  return { estimate, start };
}
