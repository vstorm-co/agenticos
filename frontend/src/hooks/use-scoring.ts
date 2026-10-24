"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { criterionNameFrom, MAX_CRITERION } from "@/lib/scoring";
import type { Dataset, DatasetCase } from "@/types/datasets";
import type {
  CaseScore,
  CaseScoreList,
  DatasetScoring,
  JudgeAgreement,
  Rescored,
  ReviewQueue,
  ScoreOutcome,
} from "@/types/scoring";

/** How many scores one request scores again: each one runs the judge. */
const RESCORE_BATCH = 10;

/** Replace how a dataset's cases are scored. Scores already kept keep theirs. */
export function useSetScoring(datasetId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scoring: DatasetScoring) =>
      apiClient.put<Dataset>(`/datasets/${datasetId}/scoring`, scoring),
    onSuccess: (dataset) => queryClient.setQueryData(qk.datasets.detail(datasetId), dataset),
  });
}

/**
 * What a dataset's own judge starts from; `instructions` null takes the dataset's
 * judge template as it is, and `model_profile_id` null the oldest model.
 */
export interface NewJudge {
  name: string;
  instructions: string | null;
  /** What the judge must know to grade - a policy, a price list - added to its instructions. */
  knowledge?: string | null;
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
      await queryClient.invalidateQueries({ queryKey: qk.agents.ofKind("judge") });
    },
  });
}

/**
 * The prompt a judge made for this dataset starts from: the default judge's rules
 * with the dataset added, for the person creating it to edit.
 */
export function useJudgeTemplate(datasetId: string) {
  const query = useQuery({
    queryKey: qk.datasets.judgeTemplate(datasetId),
    queryFn: () => apiClient.get<{ instructions: string }>(`/datasets/${datasetId}/judge-template`),
  });
  return { instructions: query.data?.instructions };
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

/** Which of a dataset's scores to read: one case's, the waiting ones, and by outcome, agent or tag. */
export interface ScoreQuery {
  caseId?: string | null;
  pending?: boolean;
  outcome?: ScoreOutcome | null;
  agentId?: string | null;
  judgeId?: string | null;
  tag?: string | null;
  skip?: number;
  limit?: number;
}

/**
 * A page of a dataset's scores, and a person's decision on one.
 *
 * `pending` narrows to the scores waiting for a decision. A decision, a request
 * for review, taking scores out of it or scoring again refreshes the dataset's
 * scores and the review queue together. Scoring again goes ten scores a request,
 * one request after another, and refreshes even when a later request fails.
 */
export function useScores(
  datasetId: string,
  {
    caseId = null,
    pending = false,
    outcome = null,
    agentId = null,
    judgeId = null,
    tag = null,
    skip = 0,
    limit = PAGE_SIZE,
  }: ScoreQuery = {},
) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: qk.datasets.scores(datasetId, {
      caseId,
      pending,
      outcome,
      agentId,
      judgeId,
      tag,
      skip,
      limit,
    }),
    queryFn: () => {
      const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
      if (caseId !== null) params.set("case_id", caseId);
      if (pending) params.set("pending", "true");
      if (outcome !== null) params.set("outcome", outcome);
      if (agentId !== null) params.set("agent_id", agentId);
      if (judgeId !== null) params.set("judge", judgeId);
      if (tag !== null) params.set("tag", tag);
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

  const rescore = useMutation({
    mutationFn: async (scoreIds: string[]) => {
      const done: Rescored = { rescored: [], kept: [] };
      for (let start = 0; start < scoreIds.length; start += RESCORE_BATCH) {
        const batch = await apiClient.post<Rescored>(`/datasets/${datasetId}/scores/rescore`, {
          score_ids: scoreIds.slice(start, start + RESCORE_BATCH),
        });
        done.rescored.push(...batch.rescored);
        done.kept.push(...batch.kept);
      }
      return done;
    },
    onSettled: changed,
  });

  const withdraw = useMutation({
    mutationFn: (scoreIds: string[]) =>
      apiClient.post<{ removed: number; kept: number }>(
        `/datasets/${datasetId}/scores/review/withdraw`,
        { score_ids: scoreIds },
      ),
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
    rescore,
    withdraw,
  };
}

/** Scores waiting for a person, across every dataset the caller may see, oldest first. */
export function useReviewQueue({
  skip = 0,
  limit = PAGE_SIZE,
  enabled = true,
}: { skip?: number; limit?: number; enabled?: boolean } = {}) {
  const query = useQuery({
    queryKey: qk.datasets.reviewQueue({ skip, limit }),
    queryFn: () => apiClient.get<ReviewQueue>(`/datasets/review-queue?skip=${skip}&limit=${limit}`),
    enabled,
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

/** How often people's decisions agreed with a judge, over the datasets the caller sees. */
export function useJudgeAgreement(judgeId: string) {
  const query = useQuery({
    queryKey: qk.datasets.judgeAgreement(judgeId),
    queryFn: () =>
      apiClient.get<JudgeAgreement>(
        `/datasets/judge-agreement?${new URLSearchParams({ judge: judgeId })}`,
      ),
  });
  return { agreement: query.data, isLoading: query.isLoading };
}

/** Where a reviewer's note becomes a judge criterion: this case alone, or every case. */
export type NoteTarget = "case" | "dataset";

/**
 * Make a reviewer's note on a score a criterion the judge grades from now on.
 *
 * For the case, it joins the newest revision's checks as a `judge` check, which
 * is a new version of the dataset. For every case, it joins the rubric and the
 * judge is switched on, which the server refuses while AI assistance is off.
 */
export function useNoteToCriterion(dataset: Dataset) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ score, target }: { score: CaseScore; target: NoteTarget }) => {
      const criterion = (score.human_note ?? "").trim().slice(0, MAX_CRITERION);
      const path = `/datasets/${dataset.id}`;
      if (target === "case") {
        const current = await apiClient.get<DatasetCase>(`${path}/cases/${score.case_id}`);
        await apiClient.patch<DatasetCase>(`${path}/cases/${score.case_id}`, {
          checks: [...current.checks, { type: "judge", criterion }],
        });
        return;
      }
      const { judge } = dataset.scoring;
      const name = criterionNameFrom(
        criterion,
        judge.criteria.map((item) => item.name),
      );
      await apiClient.put<Dataset>(`${path}/scoring`, {
        ...dataset.scoring,
        judge: {
          ...judge,
          enabled: true,
          criteria: [...judge.criteria, { name, description: criterion, required: true }],
        },
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: qk.datasets.all() }),
  });
}
