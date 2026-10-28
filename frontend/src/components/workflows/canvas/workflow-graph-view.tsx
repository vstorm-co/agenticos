"use client";

import {
  Background,
  type Connection,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  useStoreApi,
} from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";
import { useTranslations } from "next-intl";

import { ContextMenu, ContextMenuTrigger } from "@/components/ui";
import { readNodeDragData } from "@/components/workflows/palette";
import { problemText } from "@/components/workflows/property-panel/problems";
import { validateGraph } from "@/components/workflows/validation";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";

import { CanvasInteractionProvider, type ConnectEndpoint } from "./canvas-context";
import { minimapColour } from "./minimap-colour";
import { CanvasContextMenu } from "./canvas-context-menu";
import { CanvasToolbar } from "./canvas-toolbar";
import { PanePicker, type PanePoint } from "./pane-picker";
import {
  autoBindings,
  buildCatalogMap,
  definitionsByNode,
  isConnectionValid,
  toFlowEdges,
  toFlowNodes,
  type WorkflowFlowEdge,
} from "./graph-adapter";
import { withLiveScopes } from "./insertion";
import { NODE_HEIGHT, NODE_WIDTH } from "./node-size";
import { scopedGraph } from "./scope-view";
import { useInsertNode } from "./use-insert-node";
import { useCanvasShortcuts } from "./use-canvas-shortcuts";
import { edgeTypes } from "./workflow-edge";
import { nodeTypes } from "./workflow-node";
import { ShortcutSheet } from "./canvas-toolbar";
import { tidyLayout } from "./tidy";
import { type CanvasNoteNode, NOTE_HEIGHT, NOTE_WIDTH } from "./canvas-note";
import type { WorkflowFlowNode } from "./graph-adapter";

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
// Both keys, whichever a keyboard puts the delete on: macOS has only Backspace.
const DELETE_KEYS = ["Backspace", "Delete"];

const FIT_VIEW = { padding: 0.2, minZoom: 0.55, maxZoom: 1 };
/** A read-only graph is looked at whole - a run, a past version - so it may shrink further. */
const FIT_VIEW_READ_ONLY = { padding: 0.15, minZoom: 0.5, maxZoom: 1 };

/** Any button drags the empty canvas around: left, middle and right. */
const PAN_BUTTONS = [0, 1, 2];
/** How far a right press may travel and still be a click that opens a menu. */
const PAN_SLOP_PX = 4;

/** Whether the pointer travelled past the slop since the right button went down. */
function movedFrom(pressedAt: { x: number; y: number } | null, event: MouseEvent): boolean {
  return (
    pressedAt !== null &&
    Math.hypot(event.clientX - pressedAt.x, event.clientY - pressedAt.y) > PAN_SLOP_PX
  );
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
  const selection = useWorkflowEditorStore((state) => state.selection);
  const revealNodeId = useWorkflowEditorStore((state) => state.revealNodeId);
  const clearReveal = useWorkflowEditorStore((state) => state.clearReveal);
  const insert = useInsertNode(catalog);

  const { screenToFlowPosition, fitView, getZoom, flowToScreenPosition } = useReactFlow();
  const flowStore = useStoreApi();

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
  const nodes = useMemo(() => {
    const { nodeLookup } = flowStore.getState();
    const steps: Array<WorkflowFlowNode | CanvasNoteNode> = toFlowNodes(
      activeGraph,
      definitions,
      readOnly,
      selectedNodeIds,
      (nodeId) => {
        const { width, height } = nodeLookup.get(nodeId)?.measured ?? {};
        return width !== undefined && height !== undefined ? { width, height } : undefined;
      },
    );
    // Notes sit on the workflow's own canvas, never inside a loop body.
    if (scopePath.length > 0) return steps;
    const notes: CanvasNoteNode[] = (graph?.notes ?? []).map((note) => ({
      id: note.id,
      type: "note",
      position: note.layout,
      selected: selectedNodeIds.has(note.id),
      // Behind the steps, so a note under a step never catches its clicks.
      zIndex: -1,
      width: note.width ?? NOTE_WIDTH,
      height: note.height ?? NOTE_HEIGHT,
      data: { note, readOnly },
    }));
    return [...notes, ...steps];
  }, [activeGraph, definitions, readOnly, selectedNodeIds, scopePath, graph, flowStore]);
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
      x: node.layout.x + (node.layout.width ?? NODE_WIDTH),
      y: node.layout.y + (node.layout.height ?? NODE_HEIGHT),
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
  const problems = useMemo(
    () =>
      readOnly || graph === null
        ? []
        : validateGraph(graph, { items: catalog, total: catalog.length }, t),
    [readOnly, graph, catalog, t],
  );
  const problemTexts = useMemo(() => {
    const texts = new Map<string, string[]>();
    for (const problem of problems) {
      if (problem.nodeId === null) continue;
      const node = graph?.nodes.find((candidate) => candidate.id === problem.nodeId);
      const definition =
        catalog.find(
          (item) => item.id === node?.definition_id && item.version === node?.definition_version,
        ) ?? null;
      texts.set(problem.nodeId, [
        ...(texts.get(problem.nodeId) ?? []),
        problemText(problem, definition, t),
      ]);
    }
    return texts;
  }, [problems, graph, catalog, t]);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const openNode = (_event: React.MouseEvent, node: { id: string; type?: string }) => {
    if (node.type !== "note") editNode(node.id);
  };
  const addNote = useWorkflowEditorStore((state) => state.addNote);
  const moveNodes = useWorkflowEditorStore((state) => state.moveNodes);
  const minimapShown = useWorkflowEditorStore((state) => state.minimapShown);
  const nodeStyle = useWorkflowNodeStyleStore((state) => state.style);
  const setSelection = useWorkflowEditorStore((state) => state.setSelection);

  // A right click on a step opens that step's menu; on the empty canvas, the step
  // picker, where the click was - and a step picked there is placed at that point.
  const [menuNodeId, setMenuNodeId] = useState<string | null>(null);
  const [pickerAt, setPickerAt] = useState<PanePoint | null>(null);
  const menuPoint = useRef({ x: 0, y: 0 });
  // The right button also pans the canvas, and the browser still fires a context
  // menu for that drag - on Windows when it ends, on macOS and Linux as soon as
  // the button goes down. A press that moved is a pan, never a menu, so a menu
  // asked for while the button is still held waits for the release to decide.
  const rightPressAt = useRef<{ x: number; y: number } | null>(null);
  const heldPick = useRef<PanePoint | null>(null);
  const onPress = useCallback((event: MouseEvent<HTMLElement>) => {
    if (event.button === 2) rightPressAt.current = { x: event.clientX, y: event.clientY };
  }, []);
  // Released through `pointerup`: while the right button pans, xyflow's zoom
  // handler swallows the `mouseup` at the window before the canvas sees it.
  const onRelease = useCallback((event: PointerEvent<HTMLElement>) => {
    if (event.button !== 2) return;
    const pick = heldPick.current;
    heldPick.current = null;
    if (pick !== null && !movedFrom(rightPressAt.current, event)) setPickerAt(pick);
    rightPressAt.current = null;
  }, []);
  const onRightClick = useCallback(
    (event: MouseEvent<HTMLElement>) => {
      if (movedFrom(rightPressAt.current, event)) {
        rightPressAt.current = null;
        event.preventDefault();
        return;
      }
      menuPoint.current = { x: event.clientX, y: event.clientY };
      const card = event.target instanceof Element ? event.target.closest("[data-node-id]") : null;
      const nodeId = card?.getAttribute("data-node-id") ?? null;
      if (nodeId === null) {
        // Handled here, so the step menu's trigger leaves it alone.
        event.preventDefault();
        if (readOnly) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const at = { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
        // The right button still held: the release says whether this was a click.
        if ((event.buttons & 2) !== 0) {
          heldPick.current = at;
          return;
        }
        setPickerAt(at);
        rightPressAt.current = null;
        return;
      }
      rightPressAt.current = null;
      setMenuNodeId(nodeId);
      // The menu acts on what is selected, so a step right-clicked outside the
      // selection becomes the selection.
      if (!selectedNodeIds.has(nodeId)) setSelection({ nodeIds: [nodeId], edgeIds: [] });
    },
    [readOnly, selectedNodeIds, setSelection],
  );
  const interaction = useMemo(
    () => ({
      readOnly,
      connectSource,
      beginConnect,
      completeConnect,
      catalog,
      insertAfter,
      problemTexts,
    }),
    [readOnly, connectSource, beginConnect, completeConnect, catalog, insertAfter, problemTexts],
  );

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild disabled={readOnly}>
        {/* A graph editor is an application widget: role="application" tells
            assistive tech to pass keystrokes to the canvas shortcuts rather than
            read the region as document structure. The rule keys off the element
            name, so the handler it sanctions on an interactive role still needs
            the disable. */}
        {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
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
          onMouseDownCapture={onPress}
          onPointerUpCapture={onRelease}
          onContextMenuCapture={onRightClick}
          className="bg-muted/30 relative h-full min-h-[28rem] overflow-hidden outline-none"
        >
          <CanvasToolbar
            catalog={catalog}
            problems={problems}
            readOnly={readOnly}
            empty={activeGraph.nodes.length === 0}
            onAdd={(definition) => {
              // The "+" on a connection opened the picker: the step goes into it.
              const { splitEdgeId } = useWorkflowEditorStore.getState();
              const between = graph?.edges.find((edge) => edge.id === splitEdgeId);
              insert(definition, between === undefined ? {} : { between });
            }}
            onTidy={() => moveNodes(tidyLayout(activeGraph, definitions))}
          />
          <ShortcutSheet />
          <PanePicker
            at={pickerAt}
            catalog={catalog}
            onClose={() => setPickerAt(null)}
            onPick={(definition) =>
              insert(definition, { dropAt: screenToFlowPosition(menuPoint.current) })
            }
            onAddNote={
              scopePath.length === 0
                ? () => addNote(screenToFlowPosition(menuPoint.current))
                : undefined
            }
          />
          <CanvasInteractionProvider value={interaction}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onNodesChange={applyNodeChanges}
              onEdgesChange={applyEdgeChanges}
              onConnect={connect}
              // A click selects a step, to move, copy or delete it; a double click
              // opens its settings over the canvas. A drag never counts as either.
              // Read-only, nothing is selected and xyflow gives a card pointer events
              // only for a click handler, so one click opens it there.
              onNodeClick={readOnly ? openNode : undefined}
              onNodeDoubleClick={openNode}
              isValidConnection={isValid}
              nodesDraggable={!readOnly}
              nodesConnectable={!readOnly}
              elementsSelectable={!readOnly}
              deleteKeyCode={readOnly ? null : DELETE_KEYS}
              // The delete removed the focused element; hand focus back to the region.
              onDelete={focusRegion}
              colorMode={colorMode}
              // A trackpad or a wheel moves the canvas; a pinch, or Ctrl/Cmd with the
              // wheel, zooms it - the way a map or a design tool behaves.
              panOnScroll
              panOnDrag={PAN_BUTTONS}
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
              {/* Bottom-left, in a row with the minimap above it: the bottom-right
                  corner is the assistant's launcher on every dashboard page. */}
              <Controls showInteractive={false} position="bottom-left" orientation="horizontal" />
              {minimapShown && (
                <MiniMap
                  pannable
                  zoomable
                  position="bottom-left"
                  ariaLabel={t("minimapLabel")}
                  {...(nodeStyle === "colour"
                    ? { nodeColor: minimapColour }
                    : { nodeClassName: "fill-muted-foreground/40" })}
                  nodeBorderRadius={6}
                  maskColor="rgb(0 0 0 / 0.06)"
                  className="!bg-background !mb-14 !rounded-lg !border"
                />
              )}
            </ReactFlow>
          </CanvasInteractionProvider>
        </section>
      </ContextMenuTrigger>
      {!readOnly && menuNodeId !== null && (
        <CanvasContextMenu nodeId={menuNodeId} catalog={catalog} />
      )}
    </ContextMenu>
  );
}
