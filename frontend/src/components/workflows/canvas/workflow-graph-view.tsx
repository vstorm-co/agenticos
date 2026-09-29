"use client";

import { Background, type Connection, Controls, ReactFlow, useReactFlow } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useTranslations } from "next-intl";

import { readNodeDragData } from "@/components/workflows/palette";
import { validateGraph } from "@/components/workflows/validation";
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
import { NODE_HEIGHT, NODE_WIDTH, withLiveScopes } from "./insertion";
import { scopedGraph } from "./scope-view";
import { useInsertNode } from "./use-insert-node";
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

/** Frame the whole graph, but no smaller than a node's text stays legible at. */
const FIT_VIEW = { padding: 0.2, minZoom: 0.55, maxZoom: 1 };
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
  const selection = useWorkflowEditorStore((state) => state.selection);
  const revealNodeId = useWorkflowEditorStore((state) => state.revealNodeId);
  const clearReveal = useWorkflowEditorStore((state) => state.clearReveal);
  const insert = useInsertNode(catalog);

  const { screenToFlowPosition, fitView, getZoom, flowToScreenPosition } = useReactFlow();

  const [connectSource, setConnectSource] = useState<ConnectEndpoint | null>(null);
  const regionRef = useRef<HTMLElement>(null);

  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  // The store holds the whole flat graph; the canvas draws only the current
  // `foreach` scope's slice of it. Filtering here (not in the store) keeps the
  // scope switch display-only — the graph, autosave, undo and publish never see it.
  // The loop bodies are derived from the wires as they are now: the ones the
  // draft was loaded with go stale the moment a step is wired into a body.
  const activeGraph = useMemo(() => {
    const whole = graph ?? EMPTY_GRAPH;
    return scopedGraph(withLiveScopes(whole, definitionsByNode(whole, catalogMap)), scopePath);
  }, [graph, scopePath, catalogMap]);
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
      insert(definition, { dropAt: position });
    },
    [readOnly, screenToFlowPosition, insert],
  );

  // A step just added is brought into view once, framed with the step it hangs
  // off so the flow it extends stays in sight - only when it landed outside the
  // view, so a run of adds in view does not keep the canvas moving under the user.
  useEffect(() => {
    if (revealNodeId === null) return;
    const node = graph?.nodes.find((item) => item.id === revealNodeId);
    const region = regionRef.current;
    clearReveal();
    if (node === undefined || region === null) return;
    const bounds = region.getBoundingClientRect();
    const topLeft = flowToScreenPosition(node.layout);
    const bottomRight = flowToScreenPosition({
      x: node.layout.x + NODE_WIDTH,
      y: node.layout.y + NODE_HEIGHT,
    });
    const inView =
      topLeft.x >= bounds.left &&
      topLeft.y >= bounds.top &&
      bottomRight.x <= bounds.right &&
      bottomRight.y <= bounds.bottom;
    if (inView) return;
    const upstream = graph?.edges.find((edge) => edge.target_node_id === node.id);
    const framed = [{ id: node.id }, ...(upstream ? [{ id: upstream.source_node_id }] : [])];
    void fitView({ ...FIT_VIEW, maxZoom: getZoom(), nodes: framed, duration: 300 });
  }, [revealNodeId, graph, clearReveal, flowToScreenPosition, fitView, getZoom]);

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

  const insertAfter = useCallback(
    (nodeId: string, portId: string, definition: NodeDefinition) =>
      insert(definition, { from: { nodeId, portId } }),
    [insert],
  );
  // Worked out once for the whole graph, not per card: each rule reads the graph
  // around a node, and a read-only version was checked when it was published.
  const problemCounts = useMemo(() => {
    const counts = new Map<string, number>();
    if (readOnly || graph === null) return counts;
    for (const problem of validateGraph(graph, { items: catalog, total: catalog.length }, t)) {
      if (problem.nodeId !== null)
        counts.set(problem.nodeId, (counts.get(problem.nodeId) ?? 0) + 1);
    }
    return counts;
  }, [readOnly, graph, catalog, t]);
  const interaction = useMemo(
    () => ({
      readOnly,
      connectSource,
      beginConnect,
      completeConnect,
      catalog,
      insertAfter,
      problemCounts,
    }),
    [readOnly, connectSource, beginConnect, completeConnect, catalog, insertAfter, problemCounts],
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
          // A trackpad or a wheel moves the canvas; a pinch, or Ctrl/Cmd with the
          // wheel, zooms it - the way a map or a design tool behaves.
          panOnScroll
          zoomOnScroll={false}
          zoomOnPinch
          zoomOnDoubleClick={false}
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
