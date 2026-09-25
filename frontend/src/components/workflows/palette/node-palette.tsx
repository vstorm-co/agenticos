"use client";

import { useMemo, useRef } from "react";
import { Clock, GitBranch, Zap, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Pager, SearchInput, useListControls } from "@/components/ui";
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

/** The icon a row shows, by node kind — a closed set, so every entry resolves. */
const KIND_ICON: Record<NodeDefinition["kind"], LucideIcon> = {
  action: Zap,
  control: GitBranch,
  waiting: Clock,
};

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
  const groups: NodeGroup[] = [];
  const byCategory = new Map<string, NodeGroup>();
  for (const node of nodes) {
    let group = byCategory.get(node.category);
    if (group === undefined) {
      group = { category: node.category, items: [] };
      byCategory.set(node.category, group);
      groups.push(group);
    }
    group.items.push(node);
  }
  return groups;
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

  const list = useListControls({
    items: available,
    matches: (node, query) =>
      node.name.toLowerCase().includes(query) ||
      node.description.toLowerCase().includes(query) ||
      node.category.toLowerCase().includes(query),
  });

  const groups = useMemo(() => groupByCategory(list.visible), [list.visible]);

  const handleAdd = (definition: NodeDefinition) => {
    const offset = addCount.current * ADD_STAGGER;
    addCount.current += 1;
    addNode(definition, { x: ADD_ANCHOR.x + offset, y: ADD_ANCHOR.y + offset });
  };

  return (
    <section
      aria-label={t("paletteTitle")}
      data-workflow-region="palette"
      data-node-count={nodes.length}
      className="border-border space-y-3 rounded-xl border p-4"
    >
      <div className="space-y-1">
        <h2 className="text-sm font-medium">{t("paletteTitle")}</h2>
        <p className="text-muted-foreground text-xs">{t("paletteHint")}</p>
      </div>

      {nodes.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("paletteEmpty")}</p>
      ) : (
        <>
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("paletteSearch")}
          />

          {list.matched === 0 ? (
            <p className="text-muted-foreground text-sm">{t("paletteNoMatches")}</p>
          ) : (
            <div className="space-y-4">
              {groups.map((group) => (
                <div key={group.category} className="space-y-1.5">
                  <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                    {group.category}
                  </h3>
                  <ul className="space-y-1.5">
                    {group.items.map((node) => {
                      const Icon = KIND_ICON[node.kind];
                      return (
                        <li key={`${node.id}@${node.version}`}>
                          <button
                            type="button"
                            draggable
                            onDragStart={(event) => writeNodeDragData(event.dataTransfer, node)}
                            onClick={() => handleAdd(node)}
                            aria-label={t("paletteAddNode", { name: node.name })}
                            className={cn(
                              "flex w-full items-start gap-2 rounded-lg border p-2 text-left transition-colors",
                              "hover:border-foreground/20 cursor-grab active:cursor-grabbing",
                            )}
                          >
                            <Icon className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium">
                                {node.name}
                              </span>
                              {node.description && (
                                <span className="text-muted-foreground mt-0.5 block text-xs">
                                  {node.description}
                                </span>
                              )}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}

              <Pager
                page={list.page}
                pageCount={list.pageCount}
                matched={list.matched}
                total={list.total}
                onPage={list.setPage}
                counted={t("paletteNodeCount", { count: list.total })}
              />
            </div>
          )}
        </>
      )}
    </section>
  );
}
