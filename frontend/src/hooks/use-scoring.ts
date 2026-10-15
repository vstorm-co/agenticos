"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { Dataset } from "@/types/datasets";
import type { CaseScore, CaseScoreList, DatasetScoring, ReviewQueue } from "@/types/scoring";

/** Replace how a dataset's cases are scored. Scores already kept keep theirs. */
export function useSetScoring(datasetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scoring: DatasetScoring) =>
      apiClient.put<Dataset>(`/datasets/${datasetId}/scoring`, scoring),
    onSuccess: (dataset) => queryClient.setQueryData(qk.datasets.detail(datasetId), dataset),
  });
}

/** What a dataset's own judge starts from; `model_profile_id` null is the oldest model. */
export interface NewJudge {
  name: string;
  instructions: string;
  model_profile_id?: string | null;
}

/**
 * Create a judge of the dataset's own and make it the one grading the dataset.
 *
 * The dataset comes back with the judge picked, and the judges listing gains one.
 */
export function useCreateJudge(datasetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (judge: NewJudge) => apiClient.post<Dataset>(`/datasets/${datasetId}/judge`, judge),
    onSuccess: async (dataset) => {
      queryClient.setQueryData(qk.datasets.detail(datasetId), dataset);
      await queryClient.invalidateQueries({ queryKey: qk.agents.judges() });
    },
  });
}

/** Score a recorded run's answer against one case. The judge, if configured, runs now. */
export function useScoreRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      datasetId,
      caseId,
      runId,
    }: {
      datasetId: string;
      caseId: string;
      runId: string;
    }) =>
      apiClient.post<CaseScore>(`/datasets/${datasetId}/cases/${caseId}/scores`, {
        run_id: runId,
      }),
    onSuccess: (_score, { datasetId }) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.datasets.allScores(datasetId) }),
        queryClient.invalidateQueries({ queryKey: qk.datasets.allReviewQueue() }),
      ]),
  });
}

/**
 * A page of a dataset's scores, and a person's verdict on one.
 *
 * `pending` narrows to the scores waiting for a verdict. A verdict or a request
 * for review refreshes the dataset's scores and the review queue together.
 */
export function useScores(
  datasetId: string,
  {
    caseId = null,
    pending = false,
    skip = 0,
    limit = PAGE_SIZE,
  }: { caseId?: string | null; pending?: boolean; skip?: number; limit?: number } = {},
) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.datasets.scores(datasetId, { caseId, pending, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
      if (caseId !== null) params.set("case_id", caseId);
      if (pending) params.set("pending", "true");
      return apiClient.get<CaseScoreList>(`/datasets/${datasetId}/scores?${params}`);
    },
    placeholderData: (previous) => previous,
  });

  const changed = useCallback(
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.datasets.allScores(datasetId) }),
        queryClient.invalidateQueries({ queryKey: qk.datasets.allReviewQueue() }),
      ]),
    [queryClient, datasetId],
  );

  const verdict = useMutation({
    mutationFn: ({
      scoreId,
      passed,
      note,
    }: {
      scoreId: string;
      passed: boolean | null;
      note: string | null;
    }) =>
      apiClient.put<CaseScore>(`/datasets/${datasetId}/scores/${scoreId}/verdict`, {
        passed,
        note,
      }),
    onSuccess: changed,
  });

  const review = useMutation({
    mutationFn: (scoreId: string) =>
      apiClient.post<CaseScore>(`/datasets/${datasetId}/scores/${scoreId}/review`),
    onSuccess: changed,
  });

  return {
    scores: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
    verdict,
    review,
  };
}

/** Scores waiting for a person, across every dataset the caller may see, oldest first. */
export function useReviewQueue({
  skip = 0,
  limit = PAGE_SIZE,
}: { skip?: number; limit?: number } = {}) {
  const query = useQuery({
    queryKey: qk.datasets.reviewQueue({ skip, limit }),
    queryFn: () => apiClient.get<ReviewQueue>(`/datasets/review-queue?skip=${skip}&limit=${limit}`),
  });
  return {
    scores: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    datasets: query.data?.datasets ?? [],
    isLoading: query.isLoading,
    error: query.error,
    refetch: query.refetch,
  };
}
