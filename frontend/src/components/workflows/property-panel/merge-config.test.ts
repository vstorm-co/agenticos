import { describe, expect, it } from "vitest";

import {
  edge,
  echo,
  graph,
  makeCatalog,
  makeDefinition,
  node,
  port,
} from "@/components/workflows/validation/fixtures";
import { resolveDefinitions } from "@/components/workflows/validation/topology";
import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

import {
  carryBranchKey,
  fittingMergeConfig,
  fittingMergeConfigs,
  mergeBranches,
} from "./merge-config";

const IN = port("in", "input", null);
const OUT = port("out", "output", null);
const CATALOG = makeCatalog([
  makeDefinition({ id: "debug.echo", ports: [IN, OUT] }),
  makeDefinition({
    id: "logic.if",
    kind: "control",
    exclusive_branches: true,
    ports: [IN, port("true", "output", null), port("false", "output", null)],
  }),
  makeDefinition({ id: "logic.split", kind: "control", ports: [IN] }),
  makeDefinition({ id: "logic.merge", kind: "control", ports: [IN, OUT] }),
]);

const split = (id: string, ...names: string[]) =>
  node(id, "logic.split", { branches: names.map((name) => ({ name })) });
const named = (id: string, label: string): NodeInstance => ({ ...echo(id), label });

function build(nodes: NodeInstance[], wiring: [string, string, string][]): WorkflowGraph {
  return graph({
    entry: "start",
    nodes: [echo("start"), ...nodes],
    edges: wiring.map(([source, from, target], index) =>
      edge(`e${index}`, source, from, target, "in"),
    ),
  });
}

const fit = (g: WorkflowGraph, id = "J") =>
  fittingMergeConfig(g, id, resolveDefinitions(g, CATALOG));

const split2 = (config: Record<string, unknown> = {}) =>
  build(
    [split("S", "a", "b"), echo("A"), echo("B"), node("J", "logic.merge", config)],
    [
      ["start", "out", "S"],
      ["S", "a", "A"],
      ["S", "b", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );

const ifElse = (config: Record<string, unknown> = {}) =>
  build(
    [
      node("I", "logic.if", { condition: "value" }),
      echo("A"),
      echo("B"),
      node("J", "logic.merge", config),
    ],
    [
      ["start", "out", "I"],
      ["I", "true", "A"],
      ["I", "false", "B"],
      ["A", "out", "J"],
      ["B", "out", "J"],
    ],
  );

describe("fittingMergeConfig", () => {
  it("waits for all branches, named after their steps, when they run together", () => {
    expect(fit(split2())).toEqual({
      wait_for: "all",
      branch_keys: [
        { source_node_id: "A", source_port: "out", key: "debug_echo" },
        { source_node_id: "B", source_port: "out", key: "debug_echo_2" },
      ],
    });
  });

  it("names a branch after the step's own name and makes repeats unique", () => {
    const g = build(
      [
        split("S", "a", "b"),
        named("A", "Research"),
        named("B", "Research"),
        node("J", "logic.merge", {}),
      ],
      [
        ["start", "out", "S"],
        ["S", "a", "A"],
        ["S", "b", "B"],
        ["A", "out", "J"],
        ["B", "out", "J"],
      ],
    );
    expect(fit(g)?.branch_keys).toEqual([
      { source_node_id: "A", source_port: "out", key: "research" },
      { source_node_id: "B", source_port: "out", key: "research_2" },
    ]);
  });

  it("names a branch that leaves a split after the split's branch", () => {
    const g = build(
      [split("S", "left", "right"), node("J", "logic.merge", {})],
      [
        ["start", "out", "S"],
        ["S", "left", "J"],
        ["S", "right", "J"],
      ],
    );
    expect(fit(g)?.branch_keys).toEqual([
      { source_node_id: "S", source_port: "left", key: "left" },
      { source_node_id: "S", source_port: "right", key: "right" },
    ]);
  });

  it("leaves a merge of exclusive branches on the branch that ran", () => {
    expect(fit(ifElse())).toBeNull();
    expect(fit(ifElse({ wait_for: "one" }))).toBeNull();
  });

  it("switches an all-branches merge back when its branches never run together", () => {
    expect(fit(ifElse({ wait_for: "all" }))).toEqual({ wait_for: "one" });
  });

  it("leaves a merge that already fits", () => {
    const fitted = fit(split2()) as Record<string, unknown>;
    expect(fit(split2(fitted))).toBeNull();
  });

  it("keeps the names an author chose and drops those of branches that are gone", () => {
    const config = {
      wait_for: "all",
      branch_keys: [
        { source_node_id: "A", source_port: "out", key: "first" },
        { source_node_id: "gone", source_port: "out", key: "ghost" },
      ],
    };
    expect(fit(split2(config))?.branch_keys).toEqual([
      { source_node_id: "A", source_port: "out", key: "first" },
      { source_node_id: "B", source_port: "out", key: "debug_echo" },
    ]);
  });

  it("ignores malformed stored entries", () => {
    const config = { wait_for: "all", branch_keys: ["x", null, { key: 1 }] };
    expect(fit(split2(config))?.branch_keys).toHaveLength(2);
    expect(fit(split2({ wait_for: "all", branch_keys: "junk" }))?.branch_keys).toHaveLength(2);
  });

  it("does nothing for a merge with one branch, a missing node or another step", () => {
    const one = build(
      [echo("A"), node("J", "logic.merge", {})],
      [
        ["start", "out", "A"],
        ["A", "out", "J"],
      ],
    );
    expect(fit(one)).toBeNull();
    expect(fit(one, "nope")).toBeNull();
    expect(fit(one, "A")).toBeNull();
  });

  it("keeps a name that would be empty usable", () => {
    const g = build(
      [split("S", "a", "b"), named("A", "!!"), named("B", "??"), node("J", "logic.merge", {})],
      [
        ["start", "out", "S"],
        ["S", "a", "A"],
        ["S", "b", "B"],
        ["A", "out", "J"],
        ["B", "out", "J"],
      ],
    );
    expect(fit(g)?.branch_keys).toEqual([
      { source_node_id: "A", source_port: "out", key: "branch" },
      { source_node_id: "B", source_port: "out", key: "branch_2" },
    ]);
  });

  it("makes a long repeated name fit the key length", () => {
    const long = "x".repeat(40);
    const g = build(
      [split("S", "a", "b"), named("A", long), named("B", long), node("J", "logic.merge", {})],
      [
        ["start", "out", "S"],
        ["S", "a", "A"],
        ["S", "b", "B"],
        ["A", "out", "J"],
        ["B", "out", "J"],
      ],
    );
    const keys = (fit(g)?.branch_keys as { key: string }[]).map((entry) => entry.key);
    expect(keys[1]).toHaveLength(32);
    expect(keys[1]).toMatch(/_2$/);
  });
});

describe("fittingMergeConfig edge cases", () => {
  it("numbers a third branch of the same name past the second", () => {
    const g = build(
      [
        split("S", "a", "b", "c"),
        named("A", "Research"),
        named("B", "Research"),
        named("C", "Research"),
        node("J", "logic.merge", {}),
      ],
      [
        ["start", "out", "S"],
        ["S", "a", "A"],
        ["S", "b", "B"],
        ["S", "c", "C"],
        ["A", "out", "J"],
        ["B", "out", "J"],
        ["C", "out", "J"],
      ],
    );
    const keys = (fit(g)?.branch_keys as { key: string }[]).map((entry) => entry.key);
    expect(keys).toEqual(["research", "research_2", "research_3"]);
  });

  it("does nothing for a merge nothing is wired into", () => {
    expect(fit(build([node("J", "logic.merge", {})], []))).toBeNull();
  });
});

describe("mergeBranches", () => {
  it("lists the branches with their stored or default names", () => {
    const g = split2({ branch_keys: [{ source_node_id: "B", source_port: "out", key: "late" }] });
    const merge = g.nodes.find((n) => n.id === "J") as NodeInstance;
    expect(mergeBranches(g, resolveDefinitions(g, CATALOG), merge)).toEqual([
      { source_node_id: "A", source_port: "out", key: "debug_echo" },
      { source_node_id: "B", source_port: "out", key: "late" },
    ]);
  });
});

describe("fittingMergeConfigs", () => {
  it("lists only the merges that need a change, by id", () => {
    const g = split2();
    expect(fittingMergeConfigs(g, resolveDefinitions(g, CATALOG), ["J", "A"])).toEqual({
      J: expect.objectContaining({ wait_for: "all" }),
    });
    const fitted = ifElse();
    expect(fittingMergeConfigs(fitted, resolveDefinitions(fitted, CATALOG), ["J"])).toEqual({});
  });
});

describe("carryBranchKey", () => {
  const from = { nodeId: "A", port: "out" };
  const to = { nodeId: "N", port: "out" };

  it("moves the stored name to the new wire and leaves the others", () => {
    const config = {
      wait_for: "all",
      branch_keys: [
        { source_node_id: "A", source_port: "out", key: "first" },
        { source_node_id: "B", source_port: "out", key: "second" },
        "junk",
      ],
    };
    expect(carryBranchKey(config, from, to)).toEqual({
      wait_for: "all",
      branch_keys: [
        { source_node_id: "N", source_port: "out", key: "first" },
        { source_node_id: "B", source_port: "out", key: "second" },
        "junk",
      ],
    });
  });

  it("leaves a config with no list of names as it is", () => {
    const config = { wait_for: "all" };
    expect(carryBranchKey(config, from, to)).toBe(config);
  });
});
