"use client";

import { useTranslations } from "next-intl";

import type { NodeDefinition } from "@/lib/workflows/types";

interface NodePaletteProps {
  /** The node catalog the palette leaf groups by category, searches and adds from. */
  nodes: NodeDefinition[];
}

/**
 * The node palette — the seam the #1787 palette leaf fills.
 *
 * The leaf renders `nodes` grouped by category with drag-and click-to-add, a
 * search over name/description/category, and scope filtering off the editor
 * store's `scopePath`. The catalog arrives here already fetched (`useNodeCatalog`).
 */
export function NodePalette({ nodes }: NodePaletteProps) {
  const t = useTranslations("workflows");
  return (
    <section
      aria-label={t("paletteTitle")}
      data-workflow-region="palette"
      data-node-count={nodes.length}
      className="border-border space-y-1 rounded-xl border p-4"
    >
      <h2 className="text-sm font-medium">{t("paletteTitle")}</h2>
      <p className="text-muted-foreground text-xs">{t("paletteHint")}</p>
    </section>
  );
}
