"use client";

import {
  Background,
  type Connection,
  Controls,
  type OnSelectionChangeParams,
  ReactFlow,
  useReactFlow,
} from "@xyflow/react";
import { useCallback, useMemo, useState, type DragEvent } from "react";
import { useTranslations } from "next-intl";

import { readNodeDragData } from "@/components/workflows/palette";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { CanvasInteractionProvider, type ConnectEndpoint } from "./canvas-context";
import {
  buildCatalogMap,
  definitionsByNode,
  isConnectionValid,
  selectionFromFlow,
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
  /** A published version renders read-only: no dragging, connecting or handles. */
  readOnly: boolean;
}

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
  const setSelection = useWorkflowEditorStore((state) => state.setSelection);

  const { screenToFlowPosition } = useReactFlow();

  const [connectSource, setConnectSource] = useState<ConnectEndpoint | null>(null);

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
  const nodes = useMemo(
    () => toFlowNodes(activeGraph, definitions, readOnly),
    [activeGraph, definitions, readOnly],
  );
  const edges = useMemo(() => toFlowEdges(activeGraph, definitions), [activeGraph, definitions]);

  const isValid = useCallback(
    (edge: WorkflowFlowEdge | Connection): boolean => isConnectionValid(edge, definitions),
    [definitions],
  );

  const beginConnect = useCallback((endpoint: ConnectEndpoint) => setConnectSource(endpoint), []);
  const cancelConnect = useCallback(() => setConnectSource(null), []);
  const completeConnect = useCallback(
    (source: ConnectEndpoint, target: ConnectEndpoint) => {
      const connection: Connection = {
        source: source.nodeId,
        sourceHandle: source.portId,
        target: target.nodeId,
        targetHandle: target.portId,
      };
      if (isValid(connection)) connectNodes(connection);
      setConnectSource(null);
    },
    [connectNodes, isValid],
  );

  const onSelectionChange = useCallback(
    ({ nodes: selectedNodes, edges: selectedEdges }: OnSelectionChangeParams) =>
      setSelection(selectionFromFlow(selectedNodes, selectedEdges)),
    [setSelection],
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
      role="application"
      aria-label={t("canvasTitle")}
      data-workflow-region="canvas"
      data-connecting={connectSource !== null}
      onKeyDown={onKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className="border-border relative h-[32rem] overflow-hidden rounded-xl border"
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
          onConnect={connectNodes}
          onSelectionChange={onSelectionChange}
          isValidConnection={isValid}
          nodesDraggable={!readOnly}
          nodesConnectable={!readOnly}
          colorMode={colorMode}
          fitView
          proOptions={{ hideAttribution: true }}
          aria-label={t("canvasGraphLabel")}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </CanvasInteractionProvider>
    </section>
  );
}
