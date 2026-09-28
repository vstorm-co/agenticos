import { describe, expect, it } from "vitest";

import {
  bindingTargets,
  copySelection,
  danglingBindings,
  pasteClip,
  remapBindings,
} from "./clipboard";
import { sampleGraph } from "./fixtures";
import { collectIds, scopeAt } from "./typed-graph";

let counter = 0;
const newId = () => `new-${++counter}`;

describe("bindings", () => {
  it("finds the node a binding names, with or without a path", () => {
    expect(bindingTargets("a {{ x.y }} b {{z}} {{  w-1.item }}")).toEqual(["x", "z", "w-1"]);
    expect(bindingTargets("no bindings")).toEqual([]);
  });

  it("rewrites only ids in the map and leaves the rest of the text alone", () => {
    const ids = new Map([["x", "X2"]]);
    expect(remapBindings("{{ x.y }} and {{ other.y }} and x", ids)).toBe(
      "{{ X2.y }} and {{ other.y }} and x",
    );
  });
});

describe("copy and paste", () => {
  it("copies the selection and only the edges inside it", () => {
    const clip = copySelection(sampleGraph(), new Set(["start", "each-file"]));
    expect(clip.nodes.map((n) => n.id)).toEqual(["start", "each-file"]);
    expect(clip.edges.map((e) => e.id)).toEqual(["e-1"]);
  });

  it("gives every node at every depth a new id and rewrites bindings that named them", () => {
    counter = 0;
    const source = sampleGraph();
    const clip = copySelection(source, new Set(["each-file"]));
    const pasted = pasteClip(clip, newId, { x: 40, y: 40 });

    const oldIds = collectIds(source);
    const newIds = collectIds({ nodes: pasted.nodes, edges: [] });
    expect(newIds).toHaveLength(4);
    expect(newIds.some((id) => oldIds.includes(id))).toBe(false);
    expect(pasted.ids.size).toBe(4);

    const foreach = pasted.nodes[0];
    if (foreach?.config.kind !== "foreach") throw new Error("expected a foreach");
    const extract = foreach.config.body.nodes[0];
    const inner = foreach.config.body.nodes[1];
    if (extract?.config.kind !== "agent" || inner?.config.kind !== "foreach")
      throw new Error("shape");
    // The loop variable of the copied foreach now names the copy.
    expect(extract.config.prompt).toBe(`Read {{ ${foreach.id}.item }}`);
    // A sibling's output now names the copied sibling.
    expect(inner.config.items).toBe(`{{ ${extract.id}.lines }}`);
    const write = inner.config.body.nodes[0];
    if (write?.config.kind !== "table_write") throw new Error("shape");
    expect(write.config.mappings[0]?.value).toBe(`{{ ${inner.id}.item.amount }}`);
    // Not copied, so not rewritten: it still names the original start node.
    expect(foreach.config.items).toBe("{{ start.files }}");
    // The original is untouched.
    expect(scopeAt(source, ["each-file"]).nodes[0]?.config).toMatchObject({
      kind: "agent",
      prompt: "Read {{ each-file.item }}",
    });
  });

  it("moves the copy and gives its edges new ids", () => {
    counter = 0;
    const clip = copySelection(sampleGraph(), new Set(["start", "each-file"]));
    const pasted = pasteClip(clip, newId, { x: 10, y: 20 });
    expect(pasted.nodes.map((n) => n.position)).toEqual([
      { x: 10, y: 140 },
      { x: 290, y: 140 },
    ]);
    const [edge] = pasted.edges;
    expect(edge?.id).not.toBe("e-1");
    expect(edge?.source).toBe(pasted.ids.get("start"));
    expect(edge?.target).toBe(pasted.ids.get("each-file"));
  });

  it("copying a node inside a body rewrites nothing that points outside the copy", () => {
    counter = 0;
    const body = scopeAt(sampleGraph(), ["each-file"]);
    const pasted = pasteClip(copySelection(body, new Set(["extract"])), newId, { x: 0, y: 0 });
    const [agent] = pasted.nodes;
    // `each-file` was not copied, so the copy still reads the same loop item.
    expect(agent?.config).toMatchObject({ prompt: "Read {{ each-file.item }}" });
  });

  it("finds bindings that name nothing, at every depth", () => {
    const graph = sampleGraph();
    expect(danglingBindings(graph)).toEqual([]);
    const clip = copySelection(scopeAt(graph, ["each-file"]), new Set(["extract"]));
    const alone = { nodes: pasteClip(clip, newId, { x: 0, y: 0 }).nodes, edges: [] };
    expect(danglingBindings(alone)).toEqual([`${alone.nodes[0]?.id} -> each-file`]);
    expect(danglingBindings(alone, new Set(["each-file"]))).toEqual([]);
    const nested = pasteClip(
      copySelection(scopeAt(graph, ["each-file"]), new Set(["each-line"])),
      newId,
      { x: 0, y: 0 },
    );
    expect(danglingBindings({ nodes: nested.nodes, edges: [] }).length).toBeGreaterThan(0);
  });

  it("ignores bindings in nodes that hold none", () => {
    expect(
      danglingBindings({
        nodes: [{ id: "s", label: "s", position: { x: 0, y: 0 }, config: { kind: "start" } }],
        edges: [],
      }),
    ).toEqual([]);
  });
});
