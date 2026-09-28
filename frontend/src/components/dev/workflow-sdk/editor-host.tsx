"use client";

import { WorkflowBuilder } from "@workflowbuilder/sdk";
import type { OnSaveExternal, WorkflowBuilderIntegration } from "@workflowbuilder/sdk";
import { useCallback, useEffect, useMemo, useState } from "react";

import "@workflowbuilder/sdk/style.css";
import "./sdk-theme.css";

import { EditorController, type EditorApi } from "./editor-controller";
import { NODE_TYPES } from "./nodes";
import { RENDERERS } from "./renderers";
import { toSdkScope } from "./sdk-adapter";
import {
  createGuardedSave,
  createNaiveSave,
  type SaveOutcome,
  type SaveTarget,
} from "./save-handler";
import type { WorkflowGraph } from "./typed-graph";

/**
 * One mounted SDK editor.
 *
 * The SDK holds its store and registries at module level, so at most one of these
 * may be mounted per document. `activeEditor` is how this file notices the moment
 * that is violated and how a save can tell whether the editor that scheduled it
 * still exists.
 */

const JSON_FORM = { renderers: RENDERERS };

/** The editor that currently owns the SDK's global state, or null. */
let activeEditor: symbol | null = null;
let mountedEditors = 0;

/** How many editors this module believes are mounted. More than one is a bug. */
export function getMountedEditors(): number {
  return mountedEditors;
}

export type SaveMode = "guarded" | "naive";

export interface EditorHostProps {
  /** `org/workflow`; the SDK echoes it back as `name`, which the save checks. */
  name: string;
  scopePath: readonly string[];
  /**
   * The scope to edit. The SDK copies name, nodes, edges and layout direction into
   * state on its first render and ignores later props under the `props` strategy, so
   * swapping documents means remounting (the lab keys the editor on it).
   */
  initialScope: WorkflowGraph;
  getGraph: () => WorkflowGraph;
  getRevision: () => number;
  persist: SaveTarget["persist"];
  saveMode: SaveMode;
  onOutcome: (outcome: SaveOutcome) => void;
  onApi: (api: EditorApi | null) => void;
  onLog: (line: string) => void;
  /** Called with a warning when a second editor mounts while one is live. */
  onSingletonViolation?: (message: string) => void;
}

/**
 * State the SDK's long-lived callbacks read: the freshest props, the typed scope
 * behind this mount and its identity. A class so that updating it after render is a
 * method call, not a write to a value React is tracking.
 */
class Mount {
  readonly token: symbol;
  readonly scopeRef: { current: WorkflowGraph };
  readonly latest: { current: EditorHostProps };

  constructor(props: EditorHostProps) {
    this.token = Symbol(props.name);
    this.scopeRef = { current: props.initialScope };
    this.latest = { current: props };
  }

  sync(props: EditorHostProps): void {
    this.latest.current = props;
  }

  createSave(): OnSaveExternal {
    const { name, scopePath } = this.latest.current;
    const target: SaveTarget = {
      expectedName: name,
      isCurrent: () => activeEditor === this.token,
      scopePath,
      getScope: () => this.scopeRef.current,
      getGraph: () => this.latest.current.getGraph(),
      getRevision: () => this.latest.current.getRevision(),
      persist: (graph, revision) => this.latest.current.persist(graph, revision),
      onOutcome: (outcome) => this.latest.current.onOutcome(outcome),
    };
    const guarded = createGuardedSave(target);
    const naive = createNaiveSave(target);
    return (data, params) =>
      this.latest.current.saveMode === "naive" ? naive(data, params) : guarded(data, params);
  }
}

export default function EditorHost(props: EditorHostProps) {
  const { name, initialScope, onApi, onLog, onSingletonViolation } = props;

  // Everything the SDK reads once must be stable for the life of this mount.
  const [initial] = useState(() => toSdkScope(initialScope));
  // A holder object rather than a ref: the controller mutates `current` when a paste
  // adds nodes, and this is what a save re-attaches foreach bodies from.
  const [mount] = useState(() => new Mount(props));
  const { scopeRef, token } = mount;
  useEffect(() => {
    mount.sync(props);
  });

  useEffect(() => {
    const mine = token;
    if (activeEditor && activeEditor !== mine) {
      onSingletonViolation?.(
        `editor ${String(mine.description)} mounted while ${String(activeEditor.description)} was live`,
      );
    }
    activeEditor = mine;
    mountedEditors += 1;
    return () => {
      mountedEditors -= 1;
      if (activeEditor === mine) activeEditor = null;
    };
  }, [onSingletonViolation, token]);

  // One callback per mount: a new one would be a new integration for the SDK.
  const [onDataSave] = useState(() => mount.createSave());

  const integration = useMemo<WorkflowBuilderIntegration>(
    () => ({ strategy: "props", onDataSave }),
    [onDataSave],
  );

  const newId = useCallback(() => crypto.randomUUID().slice(0, 8), []);

  return (
    <WorkflowBuilder.Root
      name={name}
      nodeTypes={NODE_TYPES}
      jsonForm={JSON_FORM}
      integration={integration}
      layoutDirection="RIGHT"
      initialNodes={initial.nodes}
      initialEdges={initial.edges}
    >
      <WorkflowBuilder.DefaultLayout />
      <EditorController scopeRef={scopeRef} newId={newId} onApi={onApi} onLog={onLog} />
    </WorkflowBuilder.Root>
  );
}
