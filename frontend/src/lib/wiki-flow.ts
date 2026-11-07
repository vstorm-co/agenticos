import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { WikiGraph, WikiPage } from "./wiki-graph";
import { layoutWiki, type WikiPosition } from "./wiki-layout";

export const WIKI_COLOURS = [
  "#36a3db",
  "#ef525b",
  "#c9bd42",
  "#a475cf",
  "#4eb780",
  "#ef9c5c",
] as const;
export type WikiFlowNode = Node<
  {
    page: WikiPage;
    colour: string;
    group: string;
    incoming: number;
    outgoing: number;
    radius: number;
    showLabels: boolean;
  },
  "wiki"
>;

export type WikiGrouping = "folder" | "tag";

export function wikiGroup(page: WikiPage, grouping: WikiGrouping = "folder"): string {
  const folder = page.path.split("/").filter(Boolean).slice(0, -1).join("/") || "/";
  return grouping === "tag" ? page.tags[0] || "/" : folder;
}

export function wikiGroups(
  pages: readonly WikiPage[],
  grouping: WikiGrouping = "folder",
): string[] {
  return [...new Set(pages.map((page) => wikiGroup(page, grouping)))].sort();
}

export function wikiColour(group: string, groups: readonly string[]): string {
  return WIKI_COLOURS[groups.indexOf(group) % WIKI_COLOURS.length] ?? WIKI_COLOURS[0];
}

/** Navigation only: dragging changes this view, never note contents or their relationships. */
export function wikiFlow(
  graph: WikiGraph,
  visible: Set<string>,
  selected: string | null,
  options: { showLabels?: boolean; showArrows?: boolean; grouping?: WikiGrouping } = {},
  layout: ReadonlyMap<string, WikiPosition> = layoutWiki(graph),
) {
  const { showLabels = false, showArrows = false, grouping = "folder" } = options;
  const groups = wikiGroups(graph.pages, grouping);
  const neighbours = new Set([selected]);
  for (const edge of graph.edges) {
    if (edge.source === selected) neighbours.add(edge.target);
    if (edge.target === selected) neighbours.add(edge.source);
  }
  const nodes: WikiFlowNode[] = [...layout.values()].map(({ page, x, y }) => {
    const group = wikiGroup(page, grouping);
    return {
      id: page.path,
      ariaLabel: page.title,
      ariaRole: "button",
      type: "wiki",
      position: { x, y },
      selected: page.path === selected,
      hidden: !visible.has(page.path),
      width: 20,
      height: 20,
      style: { opacity: selected && !neighbours.has(page.path) ? 0.35 : 1 },
      data: {
        page,
        group,
        showLabels,
        radius: Math.min(
          14,
          3.5 +
            Math.sqrt(
              graph.edges.filter((edge) => edge.source === page.path || edge.target === page.path)
                .length,
            ) *
              1.6,
        ),
        colour: wikiColour(group, groups),
        incoming: graph.edges.filter((edge) => edge.target === page.path).length,
        outgoing: graph.edges.filter((edge) => edge.source === page.path).length,
      },
    };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edges: Edge[] = graph.edges.flatMap((edge) => {
    const source = byId.get(edge.source),
      target = byId.get(edge.target);
    if (!source || !target) return [];
    const active = selected === edge.source || selected === edge.target;
    const colour = active ? source.data.colour : "var(--color-muted-foreground)";
    return [
      {
        id: JSON.stringify([edge.source, edge.target]),
        source: edge.source,
        target: edge.target,
        type: "wiki",
        hidden: source.hidden || target.hidden,
        markerEnd: showArrows
          ? { type: MarkerType.ArrowClosed, color: colour, width: 12, height: 12 }
          : undefined,
        style: {
          stroke: colour,
          strokeWidth: active ? 1.2 : 0.65,
          opacity: selected && !active ? 0.06 : active ? 0.8 : 0.24,
        },
        selected: active,
        interactionWidth: 16,
      },
    ];
  });
  return { nodes, edges };
}
