import { describe, expect, it } from "vitest";

import {
  graph,
  literalBinding,
  makeCatalog,
  makeDefinition,
  node,
  nodeOutputBinding,
  port,
} from "@/components/workflows/validation/fixtures";
import type { Binding } from "@/lib/workflows/types";

import { argKeysOf } from "./code-keys";

const SOURCE = makeDefinition({
  id: "test.source",
  ports: [
    port("out", "output", {
      type: "object",
      properties: { row: { type: "object", properties: { name: {}, score: {} } } },
    }),
  ],
});
const catalog = makeCatalog([SOURCE]);

function keys(binding: Binding | null, stepData = {}) {
  const workflow = graph({
    entry: "s",
    nodes: [node("s", "test.source"), node("c", "code.python.simple")],
    bindings: binding === null ? [] : [binding],
  });
  return argKeysOf(workflow, catalog, stepData, "c");
}

describe("argKeysOf", () => {
  it("reads a literal's own keys", () => {
    expect(keys(literalBinding("c", "args", { a: 1, b: 2 }))).toEqual(["a", "b"]);
    expect(keys(literalBinding("c", "args", [1]))).toEqual([]);
  });

  it("reads the keys the last run saw, else the ones the source declares", () => {
    const bound = nodeOutputBinding("c", "args", "s", "out", ["row"]);
    expect(keys(bound, { s: { output: { row: { seen: 1 } }, error: null, runId: "r" } })).toEqual([
      "seen",
    ]);
    expect(keys(bound)).toEqual(["name", "score"]);
    expect(
      keys(bound, { s: { output: { row: "not an object" }, error: null, runId: "r" } }),
    ).toEqual(["name", "score"]);
  });

  it("has none when args is unbound, bound to a template, or to a step it does not know", () => {
    expect(keys(null)).toEqual([]);
    expect(
      keys({
        target_node_id: "c",
        target_field: "args",
        source: { kind: "template", parts: ["x"] },
      }),
    ).toEqual([]);
    expect(keys(nodeOutputBinding("c", "args", "gone", "out", []))).toEqual([]);
  });
});
