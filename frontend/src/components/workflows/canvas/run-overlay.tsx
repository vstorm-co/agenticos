"use client";

import { createContext, useContext } from "react";

import type { NodeRunStatus, WorkflowNodeRunRead } from "@/lib/workflows/types";

/** What a run did with one node of its graph, across every iteration it ran in. */
export interface NodeRunSummary {
  status: NodeRunStatus;
  /** Rows the node has in this run - one at the top level, one per iteration in a loop. */
  runs: number;
  succeeded: number;
  attempts: number;
  /** The typed `WorkflowError` a row recorded - the platform's own words. */
  problem: WorkflowNodeRunRead["error"];
  /**
   * How many items the node handed on, across its rows: the length of the one
   * list in its output. Null when an output holds no list, or more than one.
   */
  items: number | null;
  /** How long its rows took, summed: from each one's start to its end. */
  durationMs: number | null;
  /** When the row running now started, by the server's clock: a running step's timer. */
  startedAt: string | null;
}

function took(row: WorkflowNodeRunRead): number | null {
  if (row.started_at === null || row.ended_at === null) return null;
  return Date.parse(row.ended_at) - Date.parse(row.started_at);
}

/** The length of the one list among an output's fields, or null when there is not exactly one. */
export function listSize(output: Record<string, unknown> | null): number | null {
  const lists = Object.values(output ?? {}).filter((value) => Array.isArray(value));
  return lists.length === 1 ? (lists[0] as unknown[]).length : null;
}

/** The order a node's summary takes its status by: what a reader has to see first. */
const SEVERITY: NodeRunStatus[] = [
  "failed",
  "needs_attention",
  "waiting",
  "running",
  "pending",
  "cancelled",
  "succeeded",
  "skipped",
];

/** Fold a run's node rows into one summary per node instance. */
export function summarizeNodeRuns(rows: WorkflowNodeRunRead[]): Map<string, NodeRunSummary> {
  const byNode = new Map<string, NodeRunSummary>();
  for (const row of rows) {
    const current = byNode.get(row.node_instance_id);
    if (current === undefined) {
      byNode.set(row.node_instance_id, {
        status: row.status,
        runs: 1,
        succeeded: row.status === "succeeded" ? 1 : 0,
        attempts: row.attempts,
        problem: row.error,
        items: listSize(row.output),
        durationMs: took(row),
        startedAt: row.status === "running" ? row.started_at : null,
      });
      continue;
    }
    const items = listSize(row.output);
    const worse = SEVERITY.indexOf(row.status) < SEVERITY.indexOf(current.status);
    byNode.set(row.node_instance_id, {
      status: worse ? row.status : current.status,
      runs: current.runs + 1,
      succeeded: current.succeeded + (row.status === "succeeded" ? 1 : 0),
      attempts: current.attempts + row.attempts,
      problem: current.problem ?? row.error,
      items: current.items === null || items === null ? null : current.items + items,
      // Unknown until some row has both ends; a row without them adds nothing.
      durationMs:
        current.durationMs === null && took(row) === null
          ? null
          : (current.durationMs ?? 0) + (took(row) ?? 0),
      startedAt: row.status === "running" ? row.started_at : current.startedAt,
    });
  }
  return byNode;
}

/**
 * How a step reads on a run's canvas. `pending` is not yet reached in a run
 * still going; `starting` is handed its work - the step before it finished -
 * and waits only for the engine to pick it up, so it reads as under way;
 * `notReached` was never reached by a run that ended - after a failure or a
 * Stop. Each state has one look, on the card and on the wire into it.
 */
export type NodeRunState =
  | "pending"
  | "starting"
  | "running"
  | "waiting"
  | "done"
  | "failed"
  | "attention"
  | "skipped"
  | "notReached";

/** The state a step shows: its summary's status, or, with none yet, whether the run goes on. */
export function nodeRunState(summary: NodeRunSummary | null, live: boolean): NodeRunState {
  switch (summary?.status) {
    case undefined:
      return live ? "pending" : "notReached";
    case "pending":
      // Its row exists: the run has reached it, and the engine starts it next.
      return live ? "starting" : "notReached";
    case "running":
      return "running";
    case "waiting":
      return "waiting";
    case "succeeded":
      return "done";
    case "failed":
      return "failed";
    case "needs_attention":
      return "attention";
    case "skipped":
      return "skipped";
    case "cancelled":
      return "notReached";
  }
}

/** How a wire reads: by the step it leads into, once the step it leaves has done its part. */
export type WireRunState = "pending" | "running" | "done" | "failed" | "faded";

export function wireRunState(from: NodeRunState, into: NodeRunState): WireRunState {
  if (into === "skipped" || into === "notReached" || from === "skipped") return "faded";
  // A step whose policy routes its error ends failed and still hands on through
  // its error port: once the step after it is reached, the wire reads as a done one's.
  if (from !== "done" && from !== "failed") return "pending";
  if (into === "running" || into === "starting") return "running";
  if (into === "failed" || into === "attention") return "failed";
  return into === "pending" ? "pending" : "done";
}

/** A run laid over a canvas: what each step did, and whether the run is still going. */
export interface RunOverlay {
  summaries: Map<string, NodeRunSummary>;
  live: boolean;
  /**
   * Whether this canvas watched the run while it went: a failure shakes, and
   * the wire into a running step moves. A run opened after it ended stays still.
   */
  watched: boolean;
}

const NodeRunOverlayContext = createContext<RunOverlay | null>(null);

/** Colour a read-only canvas by what a run did: each node reads its own summary. */
export const NodeRunOverlayProvider = NodeRunOverlayContext.Provider;

/** This node's summary on a run's canvas, or null on the editor's. */
export function useNodeRunSummary(nodeId: string): NodeRunSummary | null {
  return useContext(NodeRunOverlayContext)?.summaries.get(nodeId) ?? null;
}

/** Whether this canvas shows a run - where a node with no summary was never reached. */
export function useIsRunView(): boolean {
  return useContext(NodeRunOverlayContext) !== null;
}

/** How this step reads on a run's canvas, and whether to move; null on the editor's. */
export function useNodeRunState(
  nodeId: string,
): { state: NodeRunState; summary: NodeRunSummary | null; watched: boolean } | null {
  const overlay = useContext(NodeRunOverlayContext);
  if (overlay === null) return null;
  const summary = overlay.summaries.get(nodeId) ?? null;
  return { state: nodeRunState(summary, overlay.live), summary, watched: overlay.watched };
}

/** How the wire between two steps reads on a run's canvas; null on the editor's. */
export function useWireRunState(from: string, into: string): WireRunState | null {
  const overlay = useContext(NodeRunOverlayContext);
  if (overlay === null) return null;
  const state = (id: string) => nodeRunState(overlay.summaries.get(id) ?? null, overlay.live);
  return wireRunState(state(from), state(into));
}

/** Live movement and one completion sweep belong only to a watched run. */
export function useRunMotion(): "live" | "finished" | null {
  const overlay = useContext(NodeRunOverlayContext);
  return overlay?.watched ? (overlay.live ? "live" : "finished") : null;
}
