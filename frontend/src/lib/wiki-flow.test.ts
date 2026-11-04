import { expect, it } from "vitest";
import { MarkerType } from "@xyflow/react";
import { buildWikiGraph, parseWikiPage } from "./wiki-graph";
import { wikiColour, wikiFlow, wikiGroup, wikiGroups } from "./wiki-flow";

it("groups notes by folder or first tag", () => {
  const tagged = parseWikiPage("notes/a.md", "---\ntags: [research]\n---\n");
  expect(wikiGroup(tagged, "tag")).toBe("research");
  expect(wikiGroups([tagged, tagged, parseWikiPage("sources/b.md", "")], "tag")).toEqual([
    "/",
    "research",
  ]);
  expect(wikiGroup(parseWikiPage("notes/a.md", ""))).toBe("notes");
  expect(wikiGroup(parseWikiPage("a.md", ""))).toBe("/");
  expect(wikiColour("research", ["notes", "research"])).toBe(
    wikiColour("research", ["notes", "research"]),
  );
  expect(wikiColour("sources", ["notes", "sources"])).not.toBe(
    wikiColour("notes", ["notes", "sources"]),
  );
});

it("draws directed arrows, dims unrelated notes, filters endpoints and preserves dragged positions", () => {
  const graph = buildWikiGraph([
    parseWikiPage("a.md", "[[b]]"),
    parseWikiPage("b.md", "[[c]]"),
    parseWikiPage("c.md", ""),
    parseWikiPage("d.md", ""),
  ]);
  const view = wikiFlow(graph, new Set(["a.md", "b.md", "c.md"]), "a.md", { showArrows: true });
  expect(view.nodes[0]).toMatchObject({
    id: "a.md",
    selected: true,
    data: { incoming: 0, outgoing: 1 },
  });
  expect(view.nodes[1]?.data.incoming).toBe(1);
  expect(view.nodes[2]?.style?.opacity).toBe(0.35);
  expect(view.nodes[3]?.hidden).toBe(true);
  expect(view.edges[0]).toMatchObject({
    source: "a.md",
    target: "b.md",
    selected: true,
    markerEnd: { type: MarkerType.ArrowClosed },
  });
  expect(view.edges[1]?.style?.opacity).toBe(0.06);
  const filtered = wikiFlow(graph, new Set(["a.md"]), "b.md");
  expect(filtered.edges.every((edge) => edge.hidden)).toBe(true);
  expect(
    wikiFlow(graph, new Set(graph.pages.map((page) => page.path)), null).nodes.every(
      (node) => node.style?.opacity === 1,
    ),
  ).toBe(true);
  expect(
    wikiFlow(
      {
        ...graph,
        edges: [
          { source: "gone", target: "a.md" },
          { source: "a.md", target: "gone" },
        ],
      },
      new Set(),
      null,
    ).edges,
  ).toEqual([]);
});
