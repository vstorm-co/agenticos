"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { listRunLogs } from "@/lib/workflows/logs-api";
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
import { toastDone } from "@/lib/toast";

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
      toastDone(t("runStarted"));
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

/**
 * The run that started this one - the caller of a workflow it ran, the run whose
 * failure it answers - for a link back to it. `refused` when the caller may not
 * open that run: its workflow is not shared with them.
 */
export function useCausingRun(runId: string | null) {
  const { data, isError } = useQuery({
    queryKey: qk.workflows.run(runId ?? ""),
    queryFn: () => getWorkflowRun(runId as string),
    enabled: runId !== null,
    // A 404 is an answer, not a blip.
    retry: false,
  });
  return { causing: data ?? null, refused: isError };
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
  // Steps and files read in the moment the run was last seen live can predate
  // its end - a step skipped in the same commit - and then nothing reads them
  // again: once a run seen live here reads as ended after them, they are read
  // once more. Only the first read of its end counts, so a later read of an
  // ended run, or one opened already ended, reads nothing twice.
  const [end, setEnd] = useState<{ runId: string; at: number | null } | null>(null);
  if (live(run.data) && end?.runId !== runId) setEnd({ runId, at: null });
  const ended = run.data !== undefined && isRunTerminal(run.data.status);
  if (ended && end?.runId === runId && end.at === null) setEnd({ runId, at: run.dataUpdatedAt });
  const endedAt = end?.runId === runId ? end.at : null;
  const nodesBehind = endedAt !== null && nodes.dataUpdatedAt > 0 && nodes.dataUpdatedAt < endedAt;
  const filesBehind = endedAt !== null && files.dataUpdatedAt > 0 && files.dataUpdatedAt < endedAt;
  useEffect(() => {
    if (nodesBehind) void queryClient.invalidateQueries({ queryKey: qk.workflows.runNodes(runId) });
    if (filesBehind) void queryClient.invalidateQueries({ queryKey: qk.workflows.runFiles(runId) });
  }, [nodesBehind, filesBehind, queryClient, runId]);
  // The lines the steps' quick logs wrote: one per settled step, so a live run's
  // are read with its steps, and once more when its end was seen after them.
  const logs = useQuery({
    queryKey: qk.workflows.runLogs(runId),
    queryFn: () => listRunLogs(runId),
    refetchInterval: live(run.data) ? LIVE_POLL_MS : false,
  });
  const logsBehind = endedAt !== null && logs.dataUpdatedAt > 0 && logs.dataUpdatedAt < endedAt;
  useEffect(() => {
    if (logsBehind) void queryClient.invalidateQueries({ queryKey: qk.workflows.runLogs(runId) });
  }, [logsBehind, queryClient, runId]);
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
      toastDone(t("runCancelled"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  const retry = useMutation({
    mutationFn: () => retryWorkflowRun(runId),
    onSuccess: (started) => {
      void queryClient.invalidateQueries({ queryKey: qk.workflows.runs(started.workflow_id) });
      toastDone(t("runRetried"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });
  return {
    run: run.data ?? null,
    isLoading: run.isLoading,
    nodes: nodes.data?.items ?? [],
    files: files.data?.items ?? [],
    logs: logs.data?.items ?? [],
    logsError: logs.error,
    graph: graph.data ?? null,
    cancel,
    retry,
  };
}
