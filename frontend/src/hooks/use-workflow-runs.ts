"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  cancelWorkflowRun,
  getWorkflowRun,
  getWorkflowRunGraph,
  listWorkflowRunFiles,
  listWorkflowRunNodes,
  listRunHistory,
  listWorkflowRuns,
  retryWorkflowRun,
  startWorkflowRun,
} from "@/lib/workflows/runs-api";
import { isRunTerminal, type RunHistoryQuery, type WorkflowRunRead } from "@/lib/workflows/types";

/** How often a live run is read again - its steps move on their own. */
const LIVE_POLL_MS = 2000;

/** A workflow's runs, and starting a new one. */
export function useWorkflowRuns(workflowId: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: qk.workflows.runs(workflowId),
    queryFn: () => listWorkflowRuns(workflowId),
    // Poll while anything on the page is still moving, and stop once all is still.
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => !isRunTerminal(run.status)) ? LIVE_POLL_MS : false,
  });
  const start = useMutation({
    mutationFn: startWorkflowRun,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.workflows.runs(workflowId) });
      toast.success(t("runStarted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading, start };
}

/** A filtered page of runs, one workflow's or every workflow's, read again while any is live. */
export function useRunHistory(query: RunHistoryQuery) {
  const { data, isLoading } = useQuery({
    queryKey: qk.workflows.runHistory(query),
    queryFn: () => listRunHistory(query),
    placeholderData: (previous) => previous,
    refetchInterval: (current) =>
      current.state.data?.items.some((run) => !isRunTerminal(run.status)) ? LIVE_POLL_MS : false,
  });
  return { runs: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/** One run - its state, its steps and its graph, read again while it is live. */
export function useWorkflowRun(runId: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const live = (run: WorkflowRunRead | undefined) =>
    run !== undefined && !isRunTerminal(run.status);
  const run = useQuery({
    queryKey: qk.workflows.run(runId),
    queryFn: () => getWorkflowRun(runId),
    refetchInterval: (query) => (live(query.state.data) ? LIVE_POLL_MS : false),
  });
  const nodes = useQuery({
    queryKey: qk.workflows.runNodes(runId),
    queryFn: () => listWorkflowRunNodes(runId),
    refetchInterval: live(run.data) ? LIVE_POLL_MS : false,
  });
  const files = useQuery({
    queryKey: qk.workflows.runFiles(runId),
    queryFn: () => listWorkflowRunFiles(runId),
    refetchInterval: live(run.data) ? LIVE_POLL_MS : false,
  });
  const graph = useQuery({
    queryKey: qk.workflows.runGraph(runId),
    queryFn: () => getWorkflowRunGraph(runId),
    staleTime: Infinity,
  });
  const cancel = useMutation({
    mutationFn: () => cancelWorkflowRun(runId),
    onSuccess: (cancelled) => {
      queryClient.setQueryData(qk.workflows.run(runId), cancelled);
      void queryClient.invalidateQueries({ queryKey: qk.workflows.runNodes(runId) });
      toast.success(t("runCancelled"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  const retry = useMutation({
    mutationFn: () => retryWorkflowRun(runId),
    onSuccess: (started) => {
      void queryClient.invalidateQueries({ queryKey: qk.workflows.runs(started.workflow_id) });
      toast.success(t("runRetried"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  return {
    run: run.data ?? null,
    isLoading: run.isLoading,
    nodes: nodes.data?.items ?? [],
    files: files.data?.items ?? [],
    graph: graph.data ?? null,
    cancel,
    retry,
  };
}
