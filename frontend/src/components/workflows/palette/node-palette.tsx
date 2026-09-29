"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";

import { SearchInput, useListControls } from "@/components/ui";
import { categoryRank, nodeVisual } from "@/components/workflows/node-visuals";
import { cn } from "@/lib/utils";
import type { NodeDefinition, NodePosition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { writeNodeDragData } from "./drag";
import { isAddableInScope } from "./scope";
import { useAddNode } from "./use-add-node";

interface NodePaletteProps {
  /** The node catalog the palette leaf groups by category, searches and adds from. */
  nodes: NodeDefinition[];
}

/**
 * Where a click-to-add node lands, and how far each successive one steps.
 *
 * The palette renders outside the canvas's `<ReactFlowProvider>`, so it cannot
 * read the viewport to drop under the cursor the way a pointer drag does. The
 * accessible add path therefore places at a fixed anchor and staggers each add
 * so a run of them does not stack on one spot; the canvas brings the new node
 * into view and the user can move it. Pointer users get cursor-accurate drops
 * through drag-and-drop instead.
 */
const ADD_ANCHOR: NodePosition = { x: 120, y: 120 };
const ADD_STAGGER = 32;

/** One category and the nodes under it, in the order the catalog first names them. */
interface NodeGroup {
  category: string;
  items: NodeDefinition[];
}

function groupByCategory(nodes: NodeDefinition[]): NodeGroup[] {
  const byCategory = new Map<string, NodeGroup>();
  for (const node of nodes) {
    const group = byCategory.get(node.category) ?? { category: node.category, items: [] };
    group.items.push(node);
    byCategory.set(node.category, group);
  }
  return [...byCategory.values()].sort(
    (a, b) =>
      categoryRank(a.category) - categoryRank(b.category) || a.category.localeCompare(b.category),
  );
}

/**
 * The node palette — the library the editor adds nodes from.
 *
 * The catalog arrives already fetched (`useNodeCatalog`). Each entry is offered
 * as a draggable, keyboard-activatable control: pointer users drag it onto the
 * canvas (payload written by {@link writeNodeDragData}, dropped by the canvas
 * leaf), and keyboard or touch users activate it to add near a fixed anchor —
 * the accessible path, since the palette sits outside the canvas's viewport.
 *
 * The offered set is scope-filtered off the store's `scopePath` first — inside a
 * `foreach` body a boundary-shaped node is hidden and a second `control.foreach`
 * blocked — then searched over name, description and category.
 */
export function NodePalette({ nodes }: NodePaletteProps) {
  const t = useTranslations("workflows");
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const addNode = useAddNode();
  const addCount = useRef(0);

  const available = useMemo(
    () => nodes.filter((node) => isAddableInScope(node, scopePath)),
    [nodes, scopePath],
  );

  // Every node on one scrolling list - the catalog is a few dozen entries, and a
  // pager hides the one a builder is looking for behind a click.
  const list = useListControls({
    items: available,
    pageSize: Number.MAX_SAFE_INTEGER,
    matches: (node, query) =>
      node.name.toLowerCase().includes(query) ||
      node.description.toLowerCase().includes(query) ||
      node.category.toLowerCase().includes(query),
  });

  const groups = useMemo(() => groupByCategory(list.visible), [list.visible]);
  const categoryLabel = (category: string) =>
    t.has(`category.${category}`) ? t(`category.${category}`) : category;

  const handleAdd = (definition: NodeDefinition) => {
    const offset = addCount.current * ADD_STAGGER;
    addCount.current += 1;
    addNode(definition, { x: ADD_ANCHOR.x + offset, y: ADD_ANCHOR.y + offset });
  };

  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const toggle = (category: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  const searching = list.query.trim() !== "";

  return (
    <section
      aria-label={t("paletteTitle")}
      data-workflow-region="palette"
      data-node-count={nodes.length}
      className="flex min-h-0 flex-col"
    >
      <div className="border-border space-y-3 border-b p-3">
        <div>
          <h2 className="text-sm font-medium">{t("paletteTitle")}</h2>
          <p className="text-muted-foreground text-xs">{t("paletteHint")}</p>
        </div>
        {nodes.length > 0 && (
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("paletteSearch")}
            className="sm:w-full"
          />
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {nodes.length === 0 ? (
          <p className="text-muted-foreground p-2 text-sm">{t("paletteEmpty")}</p>
        ) : list.matched === 0 ? (
          <p className="text-muted-foreground p-2 text-sm">{t("paletteNoMatches")}</p>
        ) : (
          <div className="space-y-1">
            {groups.map((group) => {
              const open = searching || !collapsed.has(group.category);
              return (
                <div key={group.category}>
                  <button
                    type="button"
                    aria-expanded={open}
                    onClick={() => toggle(group.category)}
                    className="text-muted-foreground hover:text-foreground flex w-full items-center justify-between rounded-md px-2 py-1.5 text-xs font-medium"
                  >
                    <span>{categoryLabel(group.category)}</span>
                    <ChevronDown
                      aria-hidden="true"
                      className={cn("size-3.5 transition-transform", !open && "-rotate-90")}
                    />
                  </button>
                  {open && (
                    <ul className="space-y-0.5 pb-1">
                      {group.items.map((node) => {
                        const visual = nodeVisual(node.id, node.category);
                        const Icon = visual.icon;
                        return (
                          <li key={`${node.id}@${node.version}`}>
                            <button
                              type="button"
                              draggable
                              onDragStart={(event) => writeNodeDragData(event.dataTransfer, node)}
                              onClick={() => handleAdd(node)}
                              aria-label={t("paletteAddNode", { name: node.name })}
                              title={node.description}
                              className={cn(
                                "hover:bg-accent flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors",
                                "focus-visible:ring-ring cursor-grab outline-none focus-visible:ring-2 active:cursor-grabbing",
                              )}
                            >
                              <span
                                className={cn(
                                  "flex size-7 shrink-0 items-center justify-center rounded-md",
                                  visual.tileClass,
                                )}
                              >
                                <Icon aria-hidden="true" className="size-3.5" />
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm">{node.name}</span>
                                {node.description && (
                                  <span className="text-muted-foreground block truncate text-xs">
                                    {node.description}
                                  </span>
                                )}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
