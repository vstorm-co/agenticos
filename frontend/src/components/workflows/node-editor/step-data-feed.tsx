"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";

import { useWorkflowRun, useWorkflowRuns } from "@/hooks";
import { stepDataOf, type StepData } from "@/lib/workflows/step-data";
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
  const mergeStepData = useWorkflowEditorStore((state) => state.mergeStepData);
  const latest = useRef({
    workflowId,
    values: new Map<string, { at: number | null; runId: string }>(),
  });
  const ids = useMemo(() => {
    const recent = runs
      .filter((run) => run.mode === "test")
      .slice(0, RECENT_RUNS)
      .map((run) => run.id)
      .reverse();
    return watched === null || recent.includes(watched) ? recent : [...recent, watched];
  }, [runs, watched]);
  const accept = useCallback(
    (runId: string, createdAt: string | null, data: Record<string, StepData>) => {
      if (latest.current.workflowId !== workflowId) {
        latest.current = { workflowId, values: new Map() };
      }
      const parsed = createdAt === null ? Number.NaN : Date.parse(createdAt);
      const at = Number.isFinite(parsed) ? parsed : null;
      const accepted: Record<string, StepData> = {};
      for (const [id, value] of Object.entries(data)) {
        const previous = latest.current.values.get(id);
        if (previous && runId !== previous.runId) {
          const previousRank = ids.indexOf(previous.runId);
          const order = at !== null && previous.at !== null ? at - previous.at : null;
          if (
            (order !== null && order < 0) ||
            ((order === null || order === 0) &&
              (previousRank < 0 || ids.indexOf(runId) < previousRank))
          )
            continue;
        }
        latest.current.values.set(id, { at, runId });
        accepted[id] = value;
      }
      if (Object.keys(accepted).length) mergeStepData(accepted);
    },
    [ids, mergeStepData, workflowId],
  );
  return ids.map((runId) => (
    <RunFeed key={runId} runId={runId} watched={runId === watched} accept={accept} />
  ));
}

function RunFeed({
  runId,
  watched,
  accept,
}: {
  runId: string;
  watched: boolean;
  accept: (runId: string, createdAt: string | null, data: Record<string, StepData>) => void;
}) {
  const { run, nodes } = useWorkflowRun(runId);
  const finishTesting = useWorkflowEditorStore((state) => state.finishTesting);

  useEffect(() => {
    const data = stepDataOf(runId, nodes);
    if (run !== null && Object.keys(data).length > 0)
      accept(runId, run.created_at ?? run.started_at, data);
  }, [runId, run, nodes, accept]);

  const ended = watched && run !== null && isRunTerminal(run.status);
  useEffect(() => {
    if (ended) finishTesting();
  }, [ended, finishTesting]);

  return null;
}
