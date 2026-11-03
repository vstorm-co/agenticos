import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { WikiGraph, WikiPage } from "./wiki-graph";
import { layoutWiki } from "./wiki-layout";

export const WIKI_COLOURS = [
  "#8b5cf6",
  "#3b82f6",
  "#14b8a6",
  "#f59e0b",
  "#ec4899",
  "#f97316",
] as const;
export type WikiFlowNode = Node<
  { page: WikiPage; colour: string; group: string; incoming: number; outgoing: number },
  "wiki"
>;

export function wikiGroup(page: WikiPage): string {
  return page.tags[0] || page.path.split("/").slice(0, -1).join("/") || "/";
}

export function wikiGroups(pages: readonly WikiPage[]): string[] {
  return [...new Set(pages.map(wikiGroup))].sort();
}

export function wikiColour(group: string, groups: readonly string[]): string {
  return WIKI_COLOURS[groups.indexOf(group) % WIKI_COLOURS.length] ?? WIKI_COLOURS[0];
}

/** Navigation only: dragging changes this view, never note contents or their relationships. */
export function wikiFlow(graph: WikiGraph, visible: Set<string>, selected: string | null) {
  const layout = layoutWiki(graph);
  const groups = wikiGroups(graph.pages);
  const neighbours = new Set([selected]);
  for (const edge of graph.edges) {
    if (edge.source === selected) neighbours.add(edge.target);
    if (edge.target === selected) neighbours.add(edge.source);
  }
  const nodes: WikiFlowNode[] = [...layout.values()].map(({ page, x, y }) => {
    const group = wikiGroup(page);
    return {
      id: page.path,
      ariaLabel: page.title,
      ariaRole: "button",
      type: "wiki",
      position: { x, y },
      selected: page.path === selected,
      hidden: !visible.has(page.path),
      width: 236,
      height: 112,
      style: { opacity: selected && !neighbours.has(page.path) ? 0.35 : 1 },
      data: {
        page,
        group,
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
    const colour = active ? source.data.colour : "#94a3b8";
    return [
      {
        id: JSON.stringify([edge.source, edge.target]),
        source: edge.source,
        target: edge.target,
        type: "default",
        hidden: source.hidden || target.hidden,
        markerEnd: { type: MarkerType.ArrowClosed, color: colour, width: 18, height: 18 },
        style: {
          stroke: colour,
          strokeWidth: active ? 2.4 : 1.5,
          opacity: selected && !active ? 0.12 : 0.7,
        },
        selected: active,
        interactionWidth: 16,
      },
    ];
  });
  return { nodes, edges };
}
