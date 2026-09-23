"use client";

import { ReactFlowProvider } from "@xyflow/react";
import { useTranslations } from "next-intl";

import type { WorkflowDetail } from "@/lib/workflows/types";

interface WorkflowCanvasProps {
  /** The workflow being edited; the canvas leaf renders its `draft_graph`. */
  workflow: WorkflowDetail;
}

/**
 * The editor canvas — the seam the #1787 canvas leaf fills.
 *
 * Already wrapped in a per-instance `<ReactFlowProvider>`, the boundary the
 * design fixes (per-instance, never a module singleton), so the leaf drops
 * `<ReactFlow>`, `<Background>`, `<Controls>`, the per-`kind` node components,
 * the typed edges and `isValidConnection` in here without re-deciding it.
 * Read-only mode (a published version) reuses this with `nodesDraggable={false}`.
 */
export function WorkflowCanvas({ workflow }: WorkflowCanvasProps) {
  const t = useTranslations("workflows");
  return (
    <ReactFlowProvider>
      <section
        aria-label={t("canvasTitle")}
        data-workflow-region="canvas"
        data-workflow-id={workflow.id}
        className="border-border flex min-h-[24rem] items-center justify-center rounded-xl border border-dashed"
      >
        <p className="text-muted-foreground text-sm">{t("canvasHint")}</p>
      </section>
    </ReactFlowProvider>
  );
}
