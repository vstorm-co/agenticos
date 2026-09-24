"use client";

import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import {
  nodeDisplayName,
  shortNodeId,
  type NodeDefinition,
  type Uuid,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { buildCatalogMap, definitionsByNode } from "./graph-adapter";

interface ScopeBreadcrumbProps {
  /** The node catalog, for resolving each `foreach` crumb's display name. */
  catalog: NodeDefinition[];
}

/**
 * The scope breadcrumb — the way back out of a nested `foreach`.
 *
 * It reads the store's `scopePath` (foreach ids root-to-current) and renders one
 * crumb per level: the root crumb resets the path to `[]`, an ancestor crumb
 * truncates the path to itself, and the current scope is a plain label. Each
 * `foreach` crumb is named from the catalog (the definition name plus a short id,
 * since #1786 gives a node instance no label of its own), falling back to the id
 * when the node or its definition is gone.
 *
 * Nothing renders at the root scope — there is no scope to leave, and entering one
 * is the node card's own control. A scope switch is display-only: clicking a crumb
 * calls `setScopePath`, which the canvas projection filters against, and touches
 * neither the graph nor the save/undo/publish paths.
 */
export function ScopeBreadcrumb({ catalog }: ScopeBreadcrumbProps) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const setScopePath = useWorkflowEditorStore((state) => state.setScopePath);

  const crumbs = useMemo<Array<{ id: Uuid; label: string }>>(() => {
    if (graph === null) return scopePath.map((id) => ({ id, label: shortNodeId(id) }));
    const definitions = definitionsByNode(graph, buildCatalogMap(catalog));
    return scopePath.map((id) => {
      const definition = definitions.get(id) ?? null;
      const label =
        definition === null ? shortNodeId(id) : nodeDisplayName(definition.name, id, true);
      return { id, label };
    });
  }, [graph, catalog, scopePath]);

  if (crumbs.length === 0) return null;

  const rootLabel = t("scopeBreadcrumbRoot");

  return (
    <nav aria-label={t("scopeBreadcrumbLabel")} className="mb-2">
      <ol className="text-muted-foreground flex flex-wrap items-center gap-1 text-sm">
        <li>
          <button
            type="button"
            onClick={() => setScopePath([])}
            aria-label={t("scopeBreadcrumbNavigate", { name: rootLabel })}
            className="hover:text-foreground underline"
          >
            {rootLabel}
          </button>
        </li>
        {crumbs.map((crumb, index) => {
          const isCurrent = index === crumbs.length - 1;
          return (
            <li key={crumb.id} className="flex items-center gap-1">
              {/* A separator glyph, not copy. */}
              <ChevronRight aria-hidden="true" className="size-3.5 shrink-0" />
              {isCurrent ? (
                <span aria-current="step" className="text-foreground font-medium">
                  {crumb.label}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setScopePath(scopePath.slice(0, index + 1))}
                  aria-label={t("scopeBreadcrumbNavigate", { name: crumb.label })}
                  className="hover:text-foreground underline"
                >
                  {crumb.label}
                </button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
