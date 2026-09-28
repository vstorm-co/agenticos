"use client";

import { useMemo } from "react";
import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import { useTranslations } from "next-intl";

import {
  CanvasInteractionProvider,
  type CanvasInteraction,
} from "@/components/workflows/canvas/canvas-context";
import {
  buildCatalogMap,
  definitionsByNode,
  toFlowEdges,
  toFlowNodes,
} from "@/components/workflows/canvas/graph-adapter";
import { edgeTypes } from "@/components/workflows/canvas/workflow-edge";
import { nodeTypes } from "@/components/workflows/canvas/workflow-node";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import type { NodeDefinition, WorkflowGraph } from "@/lib/workflows/types";

import "@xyflow/react/dist/style.css";

/**
 * A read-only preview has no connect mode; a node in it never renders a connect
 * control, so these are never reached. They throw rather than swallow, so a
 * regression that wires an editable control into the preview fails loudly.
 */
function refuseConnect(): never {
  // i18n-exempt: an internal invariant, never rendered — a read-only preview
  // hides every connect control, so this only fires on a programming error.
  throw new Error("A read-only version preview has no connect handlers");
}

/** The interaction a preview supplies: read-only, with no live connect mode. */
export const READ_ONLY_INTERACTION: CanvasInteraction = {
  readOnly: true,
  connectSource: null,
  beginConnect: refuseConnect,
  completeConnect: refuseConnect,
};

interface VersionPreviewProps {
  /** The frozen version graph to draw. */
  graph: WorkflowGraph;
  /** The node catalog, for resolving each instance's definition. */
  catalog: NodeDefinition[];
}

/**
 * A published version's graph, drawn read-only.
 *
 * The same node and edge renderers the editor canvas uses, in the same read-only
 * posture (no handles, no dragging, no connecting), but fed a frozen version
 * graph directly rather than the editor store — so opening a past version never
 * disturbs the draft being edited.
 */
export function VersionPreview({ graph, catalog }: VersionPreviewProps) {
  const t = useTranslations("workflows");
  const colorMode = useResolvedTheme();

  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  const definitions = useMemo(() => definitionsByNode(graph, catalogMap), [graph, catalogMap]);
  const nodes = useMemo(() => toFlowNodes(graph, definitions, true), [graph, definitions]);
  const edges = useMemo(() => toFlowEdges(graph, definitions), [graph, definitions]);

  return (
    <div
      data-version-preview
      className="border-border relative h-full min-h-[24rem] overflow-hidden rounded-lg border"
    >
      <ReactFlowProvider>
        <CanvasInteractionProvider value={READ_ONLY_INTERACTION}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            colorMode={colorMode}
            fitView
            proOptions={{ hideAttribution: true }}
            aria-label={t("versionPreviewLabel")}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </CanvasInteractionProvider>
      </ReactFlowProvider>
    </div>
  );
}
