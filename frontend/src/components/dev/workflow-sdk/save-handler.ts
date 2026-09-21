import type { DidSaveStatus, IntegrationDataFormat, OnSaveExternal } from "@workflowbuilder/sdk";

import { RevisionConflictError, SaveFailedError } from "./mock-workflow-api";
import { fromSdkScope } from "./sdk-adapter";
import { replaceScope, type WorkflowGraph } from "./typed-graph";

/**
 * The save callback handed to the SDK, and the two ways it can be wrong.
 *
 * The SDK's `RuntimeIntegrationWrapper` (2.3.0) reads the callback's answer with
 * `if (didSave)`. `DidSaveStatus` is `'error' | 'success' | 'alreadyStarted'`, all
 * non-empty strings, so a callback that *resolves* `'error'` is reported to the
 * user as a successful save. The only way to reach the SDK's error path is to
 * throw. `createGuardedSave` therefore resolves `'success'` after a commit and throws in
 * every other case; `createNaiveSave` is the shape the SDK's own type invites, kept here
 * so the lab can show what it does. It also skips the stale-editor and payload-name
 * checks, which is what an integration written from the SDK's documentation has.
 */

export type SaveOutcome =
  | { status: "saved"; revision: number }
  | { status: "conflict"; expectedRevision: number; serverRevision: number }
  | { status: "failed"; message: string }
  | { status: "refused"; reason: string };

export class SaveRefusedError extends Error {
  constructor(readonly reason: string) {
    super(`save refused: ${reason}`);
    this.name = "SaveRefusedError";
  }
}

export interface SaveTarget {
  /** The `name` the editor was mounted with; the SDK echoes it back in every payload. */
  expectedName: string;
  /** False once this editor has been unmounted or replaced. */
  isCurrent: () => boolean;
  scopePath: readonly string[];
  /** The typed scope this editor was mounted with, plus anything pasted into it since. */
  getScope: () => WorkflowGraph;
  getGraph: () => WorkflowGraph;
  getRevision: () => number;
  persist: (graph: WorkflowGraph, expectedRevision: number) => Promise<{ revision: number }>;
  onOutcome: (outcome: SaveOutcome) => void;
}

function outcomeOf(error: unknown): SaveOutcome {
  if (error instanceof SaveRefusedError) return { status: "refused", reason: error.reason };
  if (error instanceof RevisionConflictError) {
    return {
      status: "conflict",
      expectedRevision: error.expectedRevision,
      serverRevision: error.serverRevision,
    };
  }
  if (error instanceof SaveFailedError) {
    return { status: "failed", message: `the server answered ${error.status}` };
  }
  return { status: "failed", message: String(error) };
}

async function commit(
  target: SaveTarget,
  data: IntegrationDataFormat,
  guarded: boolean,
): Promise<SaveOutcome> {
  // The SDK's autosave timer and its beforeunload hook are not cancelled when the
  // editor unmounts, and `getStoreDataForIntegration()` reads a process-wide
  // store. A save that fires late therefore carries the *next* editor's data
  // under this editor's closure. Both checks refuse it.
  if (guarded && !target.isCurrent()) {
    throw new SaveRefusedError("the editor that scheduled this save is gone");
  }
  if (guarded && data.name !== target.expectedName) {
    throw new SaveRefusedError(
      `payload is for ${data.name}, this editor holds ${target.expectedName}`,
    );
  }
  const scope = fromSdkScope(target.getScope(), data.nodes, data.edges);
  const graph = replaceScope(target.getGraph(), target.scopePath, scope);
  const { revision } = await target.persist(graph, target.getRevision());
  return { status: "saved", revision };
}

export function createGuardedSave(target: SaveTarget): OnSaveExternal {
  return async (data): Promise<DidSaveStatus> => {
    try {
      const outcome = await commit(target, data, true);
      target.onOutcome(outcome);
      return "success";
    } catch (error) {
      target.onOutcome(outcomeOf(error));
      // Throwing is the only signal the SDK reads as failure.
      throw error;
    }
  };
}

export function createNaiveSave(target: SaveTarget): OnSaveExternal {
  return async (data): Promise<DidSaveStatus> => {
    try {
      const outcome = await commit(target, data, false);
      target.onOutcome(outcome);
      return "success";
    } catch (error) {
      target.onOutcome(outcomeOf(error));
      // What the SDK's own `DidSaveStatus` documentation suggests.
      return error instanceof RevisionConflictError ? "alreadyStarted" : "error";
    }
  };
}
