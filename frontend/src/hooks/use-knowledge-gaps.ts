"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { PAGE_SIZE } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  KnowledgeGapCasesAdded,
  KnowledgeGapStatus,
  KnowledgeGapTopicDetail,
  KnowledgeGapTopicList,
} from "@/types/knowledge-gaps";

/** Whose gaps to list: every knowledge base the caller reads, one of them, or one agent's. */
export type KnowledgeGapScope =
  { kind: "organization" } | { kind: "collection"; id: string } | { kind: "agent"; id: string };

/** A list a page shows in a tab: one knowledge base's gaps, or one agent's. */
export type KnowledgeGapPanelScope = Exclude<KnowledgeGapScope, { kind: "organization" }>;

export interface KnowledgeGapQuery {
  status?: KnowledgeGapStatus;
  skip?: number;
  limit?: number;
}

function scopePath(scope: KnowledgeGapScope): string {
  if (scope.kind === "collection") return `/knowledge-gaps/collections/${scope.id}`;
  if (scope.kind === "agent") return `/knowledge-gaps/agents/${scope.id}`;
  return "/knowledge-gaps";
}

function scopeKey(scope: KnowledgeGapScope): string {
  return scope.kind === "organization" ? scope.kind : `${scope.kind}:${scope.id}`;
}

/** A page of topics, the most asked first, and how many misses wait to be grouped. */
export function useKnowledgeGaps(
  scope: KnowledgeGapScope,
  { status = "open", skip = 0, limit = PAGE_SIZE }: KnowledgeGapQuery = {},
) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.knowledgeGaps.list(scopeKey(scope), { status, skip, limit }),
    queryFn: () => {
      const params = new URLSearchParams({ status, skip: String(skip), limit: String(limit) });
      return apiClient.get<KnowledgeGapTopicList>(`${scopePath(scope)}?${params}`);
    },
    placeholderData: (previous) => previous,
  });
  return {
    topics: data?.items ?? [],
    total: data?.total ?? 0,
    byKnowledgeBase: data?.by_knowledge_base ?? [],
    ungrouped: data?.ungrouped ?? 0,
    canRegroup: data?.can_regroup ?? false,
    unchecked: data?.unchecked ?? 0,
    isLoading,
    error,
    refetch,
  };
}

/** One topic with its newest questions and what each search found. */
export function useKnowledgeGap(topicId: string) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.knowledgeGaps.detail(topicId),
    queryFn: () => apiClient.get<KnowledgeGapTopicDetail>(`/knowledge-gaps/${topicId}`),
  });
  return { topic: data, isLoading, error, refetch };
}

/** Dismiss a topic as needing no document, or reopen it. */
export function useSetKnowledgeGapStatus() {
  const t = useTranslations("knowledgeGaps");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ topicId, status }: { topicId: string; status: KnowledgeGapStatus }) =>
      apiClient.post<KnowledgeGapTopicDetail>(
        `/knowledge-gaps/${topicId}/${status === "dismissed" ? "dismiss" : "reopen"}`,
      ),
    onSuccess: async (topic) => {
      await queryClient.invalidateQueries({ queryKey: qk.knowledgeGaps.all() });
      toast.success(topic.status === "dismissed" ? t("dismissedToast") : t("reopenedToast"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
}

/** Turn a topic's questions into cases of a dataset, in one new version. */
export function useAddKnowledgeGapToDataset() {
  const t = useTranslations("knowledgeGaps");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ topicId, datasetId }: { topicId: string; datasetId: string; name: string }) =>
      apiClient.post<KnowledgeGapCasesAdded>(`/knowledge-gaps/${topicId}/dataset`, {
        dataset_id: datasetId,
      }),
    onSuccess: async (result, { name }) => {
      await queryClient.invalidateQueries({ queryKey: qk.datasets.all() });
      toast.success(t("casesAdded", { added: result.added, skipped: result.skipped, name }));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
}

/** Group a knowledge base's waiting questions now rather than at the next pass. */
export function useRegroupKnowledgeGaps(knowledgeBaseId: string) {
  const t = useTranslations("knowledgeGaps");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiClient.post<void>(`/knowledge-gaps/collections/${knowledgeBaseId}/regroup`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.knowledgeGaps.all() });
      toast.success(t("regroupStarted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
}

/**
 * Have a model read a knowledge base's recent answers for questions it could not answer.
 *
 * The server refuses before anything runs - AI assistance off, no access - and
 * the reading lands later, announced like a grouping pass.
 */
export function useClassifyKnowledgeGaps(knowledgeBaseId: string) {
  const t = useTranslations("knowledgeGaps");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiClient.post<void>(`/knowledge-gaps/collections/${knowledgeBaseId}/classify`),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: qk.knowledgeGaps.all() });
      toast.success(t("checkStarted"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
}

/**
 * Ask the organization's drafting agent for the passage a topic is missing.
 *
 * A model run, so it can be refused - AI assistance switched off, the drafter's
 * budget spent - and the refusal is the server's, shown as it says it.
 */
export function useDraftKnowledgeGap() {
  const t = useTranslations("knowledgeGaps");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (topicId: string) =>
      apiClient.post<KnowledgeGapTopicDetail>(`/knowledge-gaps/${topicId}/draft`),
    onSuccess: async (topic) => {
      queryClient.setQueryData(qk.knowledgeGaps.detail(topic.id), topic);
      await queryClient.invalidateQueries({ queryKey: qk.knowledgeGaps.all() });
      toast.success(t("draftReady"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
}
