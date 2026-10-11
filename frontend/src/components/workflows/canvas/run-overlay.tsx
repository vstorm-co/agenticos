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
    });
  }
  return byNode;
}

const NodeRunOverlayContext = createContext<Map<string, NodeRunSummary> | null>(null);

/** Colour a read-only canvas by what a run did: each node reads its own summary. */
export const NodeRunOverlayProvider = NodeRunOverlayContext.Provider;

/** This node's summary on a run's canvas, or null on the editor's. */
export function useNodeRunSummary(nodeId: string): NodeRunSummary | null {
  return useContext(NodeRunOverlayContext)?.get(nodeId) ?? null;
}

/** Whether this canvas shows a run - where a node with no summary was never reached. */
export function useIsRunView(): boolean {
  return useContext(NodeRunOverlayContext) !== null;
}
