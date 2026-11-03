"use client";

import { useEffect, useMemo, type ReactNode } from "react";
import {
  Background,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  type NodeChange,
} from "@xyflow/react";
import { useTranslations } from "next-intl";
import { Minus, Plus, Scan } from "lucide-react";
import { Button } from "@/components/ui";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { wikiFlow, type WikiFlowNode } from "@/lib/wiki-flow";
import type { WikiGraph } from "@/lib/wiki-graph";
import { WikiNode } from "./wiki-node";
import "@xyflow/react/dist/style.css";

const NODE_TYPES = { wiki: WikiNode };

export function WikiCanvas({
  graph,
  selected,
  visible,
  onSelect,
  children,
}: {
  graph: WikiGraph;
  selected: string | null;
  visible: Set<string>;
  onSelect: (path: string | null) => void;
  children?: ReactNode;
}) {
  const colourMode = useResolvedTheme();
  const t = useTranslations("wikiGraph");
  const view = useMemo(() => wikiFlow(graph, visible, selected), [graph, visible, selected]);
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
        onNodesChange={move}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect(null)}
        nodesConnectable={false}
        edgesReconnectable={false}
        edgesFocusable={false}
        deleteKeyCode={null}
        minZoom={0.15}
        maxZoom={2}
        fitView
        fitViewOptions={{ padding: 0.3, maxZoom: 1 }}
        colorMode={colourMode}
        proOptions={{ hideAttribution: true }}
        aria-label={t("title")}
        className="!bg-background"
      >
        <Background gap={24} size={1} color="var(--color-border)" />
        <MiniMap<WikiFlowNode>
          pannable
          zoomable
          nodeColor={(node) => node.data.colour}
          nodeBorderRadius={8}
          maskColor="color-mix(in srgb, var(--color-background) 70%, transparent)"
          className="!bg-card !right-3 !bottom-16 !m-0 !hidden !overflow-hidden !rounded-xl !border !shadow-lg sm:!block"
          style={{ width: 156, height: 96 }}
          ariaLabel={t("overview")}
        />
        <Panel position="bottom-right">
          <WikiViewportControls />
        </Panel>
        {children}
      </ReactFlow>
    </ReactFlowProvider>
  );
}

function WikiViewportControls() {
  const t = useTranslations("wikiGraph");
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className="bg-card/95 flex gap-1 rounded-full border p-1 shadow-lg backdrop-blur-xl">
      <Button
        size="icon"
        variant="ghost"
        className="rounded-full"
        aria-label={t("zoomIn")}
        onClick={() => void zoomIn()}
      >
        <Plus className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="rounded-full"
        aria-label={t("zoomOut")}
        onClick={() => void zoomOut()}
      >
        <Minus className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="rounded-full"
        aria-label={t("reset")}
        onClick={() => void fitView({ padding: 0.3, maxZoom: 1 })}
      >
        <Scan className="size-4" />
      </Button>
    </div>
  );
}
