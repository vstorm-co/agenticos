"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  type NodeChange,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, CaseSensitive, Minus, Plus, Scan } from "lucide-react";
import { Button } from "@/components/ui";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { wikiFlow, type WikiFlowNode, type WikiGrouping } from "@/lib/wiki-flow";
import { layoutWiki } from "@/lib/wiki-layout";
import type { WikiGraph } from "@/lib/wiki-graph";
import { WikiNode } from "./wiki-node";
import { WikiEdge } from "./wiki-edge";
import "@xyflow/react/dist/style.css";

const NODE_TYPES = { wiki: WikiNode };
const EDGE_TYPES = { wiki: WikiEdge };

export function WikiCanvas({
  graph,
  selected,
  visible,
  onSelect,
  children,
  grouping = "folder",
}: {
  graph: WikiGraph;
  selected: string | null;
  visible: Set<string>;
  onSelect: (path: string | null) => void;
  children?: ReactNode;
  grouping?: WikiGrouping;
}) {
  const colourMode = useResolvedTheme();
  const t = useTranslations("wikiGraph");
  const [showLabels, setShowLabels] = useState(false);
  const [showArrows, setShowArrows] = useState(false);
  const layout = useMemo(() => layoutWiki(graph), [graph]);
  const view = useMemo(
    () => wikiFlow(graph, visible, selected, { showLabels, showArrows, grouping }, layout),
    [graph, visible, selected, showLabels, showArrows, grouping, layout],
  );
  const [nodes, setNodes, onNodesChange] = useNodesState<WikiFlowNode>(view.nodes);
  // Reconcile file refreshes with the canvas model: measurements and dragged positions
  // belong to React Flow and must survive a new projection of the note metadata.
  useEffect(() => {
    setNodes((previous) => {
      const existing = new Map(previous.map((node) => [node.id, node]));
      return view.nodes.map((node) => ({
        ...existing.get(node.id),
        ...node,
        position: existing.get(node.id)?.position ?? node.position,
      }));
    });
  }, [view.nodes, setNodes]);
  const move = (changes: NodeChange<WikiFlowNode>[]) => {
    onNodesChange(changes);
    for (const change of changes) {
      if (change.type === "select" && change.selected) onSelect(change.id);
    }
  };
  return (
    <ReactFlowProvider>
      <ReactFlow<WikiFlowNode>
        nodes={nodes}
        edges={view.edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={move}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        edgesReconnectable={false}
        edgesFocusable={false}
        deleteKeyCode={null}
        minZoom={0.15}
        maxZoom={4}
        fitView
        fitViewOptions={{ padding: 0.3, maxZoom: 1.8 }}
        colorMode={colourMode}
        proOptions={{ hideAttribution: true }}
        aria-label={t("title")}
        className="!bg-background"
      >
        <MiniMap<WikiFlowNode>
          pannable
          zoomable
          nodeColor={(node) => node.data.colour}
          nodeBorderRadius={100}
          maskColor="color-mix(in srgb, var(--color-background) 70%, transparent)"
          className="!bg-card !right-3 !bottom-16 !m-0 !hidden !overflow-hidden !rounded-xl !border !shadow-lg sm:!block"
          style={{ width: 156, height: 96 }}
          ariaLabel={t("overview")}
        />
        <Panel position="bottom-right">
          <WikiViewportControls
            showLabels={showLabels}
            showArrows={showArrows}
            onLabels={() => setShowLabels(!showLabels)}
            onArrows={() => setShowArrows(!showArrows)}
          />
        </Panel>
        {children}
      </ReactFlow>
    </ReactFlowProvider>
  );
}

function WikiViewportControls({
  showLabels,
  showArrows,
  onLabels,
  onArrows,
}: {
  showLabels: boolean;
  showArrows: boolean;
  onLabels: () => void;
  onArrows: () => void;
}) {
  const t = useTranslations("wikiGraph");
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className="bg-card/95 grid grid-cols-6 gap-1 rounded-2xl border p-1 shadow-lg backdrop-blur-xl sm:flex sm:rounded-full">
      <Button
        size="icon"
        variant={showLabels ? "secondary" : "ghost"}
        className="col-span-3 rounded-full"
        aria-label={t("showLabels")}
        aria-pressed={showLabels}
        onClick={onLabels}
      >
        <CaseSensitive className="size-4" />
      </Button>
      <Button
        size="icon"
        variant={showArrows ? "secondary" : "ghost"}
        className="col-span-3 rounded-full"
        aria-label={t("showArrows")}
        aria-pressed={showArrows}
        onClick={onArrows}
      >
        <ArrowUpRight className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="col-span-2 rounded-full"
        aria-label={t("zoomIn")}
        onClick={() => void zoomIn()}
      >
        <Plus className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="col-span-2 rounded-full"
        aria-label={t("zoomOut")}
        onClick={() => void zoomOut()}
      >
        <Minus className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="col-span-2 rounded-full"
        aria-label={t("reset")}
        onClick={() => void fitView({ padding: 0.3, maxZoom: 1.8 })}
      >
        <Scan className="size-4" />
      </Button>
    </div>
  );
}
