"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { validateGraph } from "@/components/workflows/validation";
import { useNodeCatalog } from "@/hooks";
import type { NodeCatalog, Uuid } from "@/lib/workflows/types";

import { PanelShell } from "./panel-shell";
import { usePanelStore } from "./store-bridge";

/**
 * The docked property panel — the store-connected shell around the form renderer.
 *
 * It reads the selected node and the working graph through the store's graph seam
 * (added by the canvas leaf in parallel, see `store-bridge.ts`), the node catalog
 * from its query, and runs the client-side validation mirror over the graph so the
 * shell can show per-field messages, a per-node warning badge and the footer
 * problems list. Selecting a problem re-selects its node through the store.
 */
export function PropertyPanel() {
  const t = useTranslations("workflows");
  const store = usePanelStore();
  const { nodes, isLoading } = useNodeCatalog();
  const catalog: NodeCatalog = useMemo(() => ({ items: nodes, total: nodes.length }), [nodes]);

  const graph = store.getGraph();
  const selectedNode = store.getSelectedNode();

  const problems = useMemo(
    () => (graph !== null && !isLoading ? validateGraph(graph, catalog, t) : []),
    [graph, catalog, isLoading, t],
  );

  const selectNode = (nodeId: Uuid) => store.setSelection({ nodeIds: [nodeId], edgeIds: [] });

  return (
    <PanelShell
      graph={graph}
      selectedNode={selectedNode}
      selection={store.selection}
      catalog={catalog}
      problems={problems}
      updateNodeConfig={store.updateNodeConfig}
      upsertBinding={store.upsertBinding}
      removeBinding={store.removeBinding}
      onSelectNode={selectNode}
    />
  );
}
