"use client";

import { Background, type Connection, Controls, ReactFlow, useReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useTranslations } from "next-intl";

import { readNodeDragData } from "@/components/workflows/palette";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { CanvasInteractionProvider, type ConnectEndpoint } from "./canvas-context";
import {
  autoBindings,
  buildCatalogMap,
  definitionsByNode,
  isConnectionValid,
  toFlowEdges,
  toFlowNodes,
  type WorkflowFlowEdge,
} from "./graph-adapter";
import { scopedGraph } from "./scope-view";
import { useCanvasShortcuts } from "./use-canvas-shortcuts";
import { edgeTypes } from "./workflow-edge";
import { nodeTypes } from "./workflow-node";

interface WorkflowGraphViewProps {
  /** The node catalog, for resolving each instance's definition and connection rules. */
  catalog: NodeDefinition[];
  /**
   * A published version renders read-only: no dragging, connecting, selecting or
   * deleting. Port handles still mount (non-interactive) so xyflow can position
   * the edges that reference them.
   */
  readOnly: boolean;
}

/** Frame a graph close enough to read: below 0.8 a node's text stops being legible. */
const FIT_VIEW = { padding: 0.2, minZoom: 0.8, maxZoom: 1 };
/** A read-only graph is looked at whole - a run, a past version - so it may shrink further. */
const FIT_VIEW_READ_ONLY = { padding: 0.15, minZoom: 0.5, maxZoom: 1 };

/** The graph a blank editor shows before the page has seeded a draft. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/**
 * The controlled `<ReactFlow>` — nodes and edges projected from the store's
 * working graph, every change applied back to the store.
 *
 * Selection flows to the store (`setSelection`) so the palette, panel and
 * clipboard read one selection. `isValidConnection` refuses an incompatible drag
 * before it draws (rule 3), and the same check gates the keyboard connect mode.
 * Must render inside a `<ReactFlowProvider>` (the canvas shell supplies it).
 */
export function WorkflowGraphView({ catalog, readOnly }: WorkflowGraphViewProps) {
  const t = useTranslations("workflows");
  const colorMode = useResolvedTheme();

  const graph = useWorkflowEditorStore((state) => state.graph);
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const applyNodeChanges = useWorkflowEditorStore((state) => state.applyNodeChanges);
  const applyEdgeChanges = useWorkflowEditorStore((state) => state.applyEdgeChanges);
  const connectNodes = useWorkflowEditorStore((state) => state.connectNodes);
  const addNode = useWorkflowEditorStore((state) => state.addNode);
  const selection = useWorkflowEditorStore((state) => state.selection);

  const { screenToFlowPosition, fitView } = useReactFlow();

  const [connectSource, setConnectSource] = useState<ConnectEndpoint | null>(null);
  const regionRef = useRef<HTMLElement>(null);

  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  // The store holds the whole flat graph; the canvas draws only the current
  // `foreach` scope's slice of it. Filtering here (not in the store) keeps the
  // scope switch display-only — the graph, autosave, undo and publish never see it.
  const activeGraph = useMemo(
    () => scopedGraph(graph ?? EMPTY_GRAPH, scopePath),
    [graph, scopePath],
  );
  const definitions = useMemo(
    () => definitionsByNode(activeGraph, catalogMap),
    [activeGraph, catalogMap],
  );
  const selectedNodeIds = useMemo(() => new Set(selection.nodeIds), [selection.nodeIds]);
  const selectedEdgeIds = useMemo(() => new Set(selection.edgeIds), [selection.edgeIds]);
  const nodes = useMemo(
    () => toFlowNodes(activeGraph, definitions, readOnly, selectedNodeIds),
    [activeGraph, definitions, readOnly, selectedNodeIds],
  );
  const edges = useMemo(
    () => toFlowEdges(activeGraph, definitions, selectedEdgeIds),
    [activeGraph, definitions, selectedEdgeIds],
  );

  const isValid = useCallback(
    (edge: WorkflowFlowEdge | Connection): boolean => isConnectionValid(edge, definitions),
    [definitions],
  );

  // An edge orders two steps; the values a step reads are bindings. When the ports
  // match exactly the wiring is unambiguous, so the edge brings its bindings with it.
  const connect = useCallback(
    (connection: Connection) =>
      connectNodes(connection, autoBindings(connection, graph ?? EMPTY_GRAPH, definitions)),
    [connectNodes, graph, definitions],
  );

  // Starting and completing a connection swap the buttons for others, so the one
  // that was clicked unmounts and takes focus with it; put it back on the region.
  const focusRegion = useCallback(() => regionRef.current?.focus(), []);
  const beginConnect = useCallback(
    (endpoint: ConnectEndpoint) => {
      setConnectSource(endpoint);
      focusRegion();
    },
    [focusRegion],
  );
  const cancelConnect = useCallback(() => setConnectSource(null), []);
  const completeConnect = useCallback(
    (source: ConnectEndpoint, target: ConnectEndpoint) => {
      const connection: Connection = {
        source: source.nodeId,
        sourceHandle: source.portId,
        target: target.nodeId,
        targetHandle: target.portId,
      };
      if (isValid(connection)) connect(connection);
      setConnectSource(null);
      focusRegion();
    },
    [connect, isValid, focusRegion],
  );

  // Drag-from-palette: the palette writes the whole definition onto the drag; the
  // canvas owns the viewport, so it alone resolves the drop point to graph
  // coordinates and calls the store's `addNode`. A drop from anywhere else carries
  // no palette payload and is ignored.
  const onDragOver = useCallback(
    (event: DragEvent) => {
      if (readOnly) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [readOnly],
  );
  const onDrop = useCallback(
    (event: DragEvent) => {
      if (readOnly) return;
      event.preventDefault();
      const definition = readNodeDragData(event.dataTransfer);
      if (!definition) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      addNode(definition, position);
    },
    [readOnly, screenToFlowPosition, addNode],
  );

  // A different scope is a different drawing: frame it, or entering a loop body
  // leaves the viewport where the outer graph was and the body off-screen.
  const scopeKey = scopePath.join("/");
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      void fitView(readOnly ? FIT_VIEW_READ_ONLY : FIT_VIEW);
    });
    return () => cancelAnimationFrame(frame);
  }, [scopeKey, fitView, readOnly]);

  const onKeyDown = useCanvasShortcuts(readOnly, cancelConnect);

  const interaction = useMemo(
    () => ({ readOnly, connectSource, beginConnect, completeConnect }),
    [readOnly, connectSource, beginConnect, completeConnect],
  );

  return (
    // A graph editor is an application widget: role="application" tells assistive
    // tech to pass keystrokes to the canvas shortcuts rather than read the region
    // as document structure. The rule keys off the element name, so the handler it
    // sanctions on an interactive role still needs the disable.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <section
      ref={regionRef}
      role="application"
      // Focusable, though not a tab stop, so a click anywhere in the canvas puts focus
      // on the region the shortcuts listen on. Otherwise a click on empty canvas, or on
      // a button in Firefox and Safari on macOS (which do not focus a clicked button),
      // leaves focus on the page and Cmd+C, Cmd+V and Cmd+Z do nothing.
      tabIndex={-1}
      aria-label={t("canvasTitle")}
      data-workflow-region="canvas"
      data-connecting={connectSource !== null}
      onKeyDown={onKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className="bg-muted/30 relative h-full min-h-[28rem] overflow-hidden outline-none"
    >
      {activeGraph.nodes.length === 0 && (
        <p className="text-muted-foreground pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-4 text-center text-sm">
          {t("canvasHint")}
        </p>
      )}
      <CanvasInteractionProvider value={interaction}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={applyNodeChanges}
          onEdgesChange={applyEdgeChanges}
          onConnect={connect}
          isValidConnection={isValid}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          elementsSelectable={!readOnly}
          deleteKeyCode={readOnly ? null : "Backspace"}
          // The delete removed the focused element; hand focus back to the region.
          onDelete={focusRegion}
          colorMode={colorMode}
          fitView
          fitViewOptions={readOnly ? FIT_VIEW_READ_ONLY : FIT_VIEW}
          minZoom={0.3}
          proOptions={{ hideAttribution: true }}
          aria-label={t("canvasGraphLabel")}
        >
          <Background gap={20} size={1.5} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
      </CanvasInteractionProvider>
    </section>
  );
}
