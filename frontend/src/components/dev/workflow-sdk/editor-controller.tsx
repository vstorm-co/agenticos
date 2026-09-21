"use client";

import {
  getStoreEdges,
  getStoreNodes,
  getStoreSelection,
  setStoreEdges,
  setStoreNodes,
  trackFutureChange,
  useStore,
  useWorkflowBuilderActions,
} from "@workflowbuilder/sdk";
import type {
  DidSaveStatus,
  Theme,
  WorkflowBuilderEdge,
  WorkflowBuilderNode,
} from "@workflowbuilder/sdk";
import { useEffect, useRef } from "react";

import { copySelection, pasteClip, type Clip } from "./clipboard";
import { History, Recorder } from "./history";
import { fromSdkScope, toSdkScope } from "./sdk-adapter";
import type { WorkflowGraph } from "./typed-graph";

/**
 * Undo/redo and copy/paste for one mounted editor.
 *
 * Rendered as a child of `<WorkflowBuilder.Root>` so it can use the SDK's
 * process-wide store. It draws nothing; the lab drives it through `EditorApi`.
 */

interface Snapshot {
  nodes: WorkflowBuilderNode[];
  edges: WorkflowBuilderEdge[];
}

export interface EditorApi {
  undo: () => void;
  redo: () => void;
  copy: () => number;
  cut: () => number;
  paste: () => number;
  /** The live editor state read back as a typed scope. Throws `GraphParseError` when it is invalid. */
  scope: () => WorkflowGraph;
  selectedIds: () => string[];
  /** The SDK's own save, through the integration context. */
  save: () => Promise<DidSaveStatus>;
  setTheme: (theme: Theme) => void;
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  readonly historySize: number;
}

/**
 * What identifies an edit. The SDK rewrites `selected`, `measured`, `dragging` and
 * the derived `properties.errors` on nodes that were not edited, so comparing the
 * arrays would record a history entry for a click.
 */
function semanticKey(
  nodes: readonly WorkflowBuilderNode[],
  edges: readonly WorkflowBuilderEdge[],
): string {
  return JSON.stringify([
    nodes.map((node) => {
      const { errors: _e, customErrors: _c, ...properties } = node.data.properties;
      void _e;
      void _c;
      return [node.id, node.position.x, node.position.y, node.data.type, properties];
    }),
    edges.map((edge) => [edge.id, edge.source, edge.target]),
  ]);
}

function snapshot(): Snapshot {
  return { nodes: structuredClone(getStoreNodes()), edges: structuredClone(getStoreEdges()) };
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

let clipboard: Clip | null = null;

interface Props {
  /** The typed scope behind this editor. Pasted foreach bodies are added to it. */
  scopeRef: { current: WorkflowGraph };
  newId: () => string;
  onApi: (api: EditorApi | null) => void;
  onLog: (line: string) => void;
}

export function EditorController({ scopeRef, newId, onApi, onLog }: Props) {
  const actions = useWorkflowBuilderActions();
  const actionsRef = useRef(actions);
  useEffect(() => {
    actionsRef.current = actions;
  });

  // The SDK keeps its own theme (`data-theme` on <html>, persisted under `wb-theme`);
  // the console keeps a `light` / `dark` class on the same element. Follow the console.
  useEffect(() => {
    const root = document.documentElement;
    const follow = () =>
      actionsRef.current.setTheme(root.classList.contains("dark") ? "dark" : "light");
    follow();
    const observer = new MutationObserver(follow);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const history = new History<Snapshot>();
    const recorder = new Recorder<Snapshot>(history, () => ({
      key: semanticKey(getStoreNodes(), getStoreEdges()),
      snapshot: snapshot(),
    }));
    let restoring = false;

    // `loadData` runs in an ancestor's effect, after this one. A macrotask later the
    // store holds the loaded diagram, and that is the baseline, not an edit.
    const baseline = setTimeout(() => recorder.baseline(), 0);

    const unsubscribe = useStore.subscribe((state, previous) => {
      if (restoring) return;
      if (state.nodes === previous.nodes && state.edges === previous.edges) return;
      // One entry per gesture is the unit a person undoes.
      recorder.schedule();
    });

    const restore = (target: Snapshot | null) => {
      if (!target) return;
      restoring = true;
      setStoreNodes(structuredClone(target.nodes));
      setStoreEdges(structuredClone(target.edges));
      recorder.restored(semanticKey(target.nodes, target.edges));
      trackFutureChange("undoRedo");
      // The store notifies synchronously; release on the next tick.
      setTimeout(() => {
        restoring = false;
      }, 0);
    };

    const selectedIds = () => new Set(getStoreSelection().nodes.map((node) => node.id));

    const currentScope = (): WorkflowGraph =>
      fromSdkScope(scopeRef.current, getStoreNodes(), getStoreEdges());

    const copy = (): number => {
      const ids = selectedIds();
      if (ids.size === 0) return 0;
      clipboard = copySelection(currentScope(), ids);
      return clipboard.nodes.length;
    };

    const paste = (): number => {
      if (!clipboard) return 0;
      const pasted = pasteClip(clipboard, newId, { x: 40, y: 40 });
      // The SDK never holds a foreach body, so the typed scope must learn the new
      // nodes or the next save would re-attach empty bodies to them.
      scopeRef.current = {
        nodes: [...scopeRef.current.nodes, ...pasted.nodes],
        edges: scopeRef.current.edges,
      };
      const sdk = toSdkScope({ nodes: pasted.nodes, edges: pasted.edges });
      setStoreNodes([
        ...getStoreNodes().map((node) => ({ ...node, selected: false })),
        ...sdk.nodes.map((node) => ({ ...node, selected: true })),
      ]);
      setStoreEdges([...getStoreEdges(), ...sdk.edges]);
      trackFutureChange("paste");
      return pasted.nodes.length;
    };

    const cut = (): number => {
      const count = copy();
      if (count === 0) return 0;
      const ids = selectedIds();
      setStoreNodes(getStoreNodes().filter((node) => !ids.has(node.id)));
      setStoreEdges(
        getStoreEdges().filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)),
      );
      trackFutureChange("delete");
      return count;
    };

    const api: EditorApi = {
      undo: () => restore(recorder.undo()),
      redo: () => restore(recorder.redo()),
      copy,
      cut,
      paste,
      scope: currentScope,
      selectedIds: () => [...selectedIds()],
      save: () => actionsRef.current.save(),
      setTheme: (theme) => actionsRef.current.setTheme(theme),
      get canUndo() {
        return history.canUndo;
      },
      get canRedo() {
        return history.canRedo;
      },
      get historySize() {
        return history.size;
      },
    };
    onApi(api);

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      const key = event.key.toLowerCase();
      try {
        if (key === "z" && !event.shiftKey) api.undo();
        else if ((key === "z" && event.shiftKey) || key === "y") api.redo();
        else if (key === "c") onLog(`copied ${api.copy()} node(s)`);
        else if (key === "x") onLog(`cut ${api.cut()} node(s)`);
        else if (key === "v") onLog(`pasted ${api.paste()} node(s)`);
        else return;
      } catch (error) {
        onLog(`${key}: ${String(error)}`);
      }
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      unsubscribe();
      clearTimeout(baseline);
      recorder.cancel();
      onApi(null);
    };
  }, [scopeRef, newId, onApi, onLog]);

  return null;
}
