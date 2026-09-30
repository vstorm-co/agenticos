"use client";

import { useEffect } from "react";

import { useWorkflowRun, useWorkflowRuns } from "@/hooks";
import { stepDataOf } from "@/lib/workflows/step-data";
import { isRunTerminal } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/**
 * Keeps the editor's step data current: what each step of the last test run
 * handed on - the latest one found on opening, then each one started from the
 * editor, a whole run or a single step's - folded in as the run moves.
 */
export function StepDataFeed({ workflowId }: { workflowId: string }) {
  const { runs } = useWorkflowRuns(workflowId);
  const watched = useWorkflowEditorStore((state) => state.watchedRunId);
  const runId = watched ?? runs.find((run) => run.mode === "test")?.id ?? null;
  return runId === null ? null : <RunFeed key={runId} runId={runId} />;
}

function RunFeed({ runId }: { runId: string }) {
  const { run, nodes } = useWorkflowRun(runId);
  const mergeStepData = useWorkflowEditorStore((state) => state.mergeStepData);
  const finishTesting = useWorkflowEditorStore((state) => state.finishTesting);

  useEffect(() => {
    const data = stepDataOf(runId, nodes);
    if (Object.keys(data).length > 0) mergeStepData(data);
  }, [runId, nodes, mergeStepData]);

  const ended = run !== null && isRunTerminal(run.status);
  useEffect(() => {
    if (ended) finishTesting();
  }, [ended, finishTesting]);

  return null;
}
