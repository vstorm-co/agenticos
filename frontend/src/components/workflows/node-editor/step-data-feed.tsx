"use client";

import { useEffect } from "react";

import { useWorkflowRun, useWorkflowRuns } from "@/hooks";
import { stepDataOf } from "@/lib/workflows/step-data";
import { isRunTerminal } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/** Test runs read on opening: a step test runs only part of a graph, so one is not enough. */
const RECENT_RUNS = 5;

/**
 * Keeps the editor's step data current: what each step handed on in the recent
 * test runs found on opening, oldest first so the newest wins, then in each one
 * started from the editor - a whole run or a single step's - as the run moves.
 */
export function StepDataFeed({ workflowId }: { workflowId: string }) {
  const { runs } = useWorkflowRuns(workflowId);
  const watched = useWorkflowEditorStore((state) => state.watchedRunId);
  const recent = runs
    .filter((run) => run.mode === "test")
    .slice(0, RECENT_RUNS)
    .map((run) => run.id)
    .reverse();
  const ids = watched === null || recent.includes(watched) ? recent : [...recent, watched];
  return ids.map((runId) => <RunFeed key={runId} runId={runId} watched={runId === watched} />);
}

function RunFeed({ runId, watched }: { runId: string; watched: boolean }) {
  const { run, nodes } = useWorkflowRun(runId);
  const mergeStepData = useWorkflowEditorStore((state) => state.mergeStepData);
  const finishTesting = useWorkflowEditorStore((state) => state.finishTesting);

  useEffect(() => {
    const data = stepDataOf(runId, nodes);
    if (Object.keys(data).length > 0) mergeStepData(data);
  }, [runId, nodes, mergeStepData]);

  const ended = watched && run !== null && isRunTerminal(run.status);
  useEffect(() => {
    if (ended) finishTesting();
  }, [ended, finishTesting]);

  return null;
}
