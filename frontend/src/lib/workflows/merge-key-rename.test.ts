import { describe, expect, it } from "vitest";

import { carryMergeKeyRename, mergeKeyRename } from "./merge-key-rename";
import type { Binding, NodeInstance, WorkflowGraph } from "./types";

const merge = (...keys: string[]): NodeInstance => ({
  id: "m",
  definition_id: "logic.merge",
  definition_version: 1,
  config: {
    wait_for: "all",
    branch_keys: keys.map((key, index) => ({
      source_node_id: `s${index}`,
      source_port: "out",
      key,
    })),
  },
  layout: { x: 0, y: 0 },
});

const read = (key: string, node = "m"): Binding => ({
  target_node_id: "t",
  target_field: "f",
  source: { kind: "node_output", node_id: node, port: "value", field_path: ["branches", key] },
});

const graphOf = (node: NodeInstance, ...bindings: Binding[]): WorkflowGraph => ({
  entry_node_id: "m",
  nodes: [node],
  edges: [],
  bindings,
  scopes: [],
});

describe("mergeKeyRename", () => {
  it("names the one branch whose key changed", () => {
    const before = merge("a", "b");
    expect(mergeKeyRename(before, merge("a", "c").config, graphOf(before))).toEqual({
      from: "b",
      to: "c",
    });
  });

  it("carries nothing for another step, a missing list, a changed length or two changes", () => {
    const before = merge("a", "b");
    const g = graphOf(before);
    expect(mergeKeyRename({ ...before, definition_id: "x" }, merge("a", "c").config, g)).toBeNull();
    expect(mergeKeyRename(before, {}, g)).toBeNull();
    expect(mergeKeyRename({ ...before, config: {} }, merge("a", "b").config, g)).toBeNull();
    expect(mergeKeyRename(before, merge("a").config, g)).toBeNull();
    expect(mergeKeyRename(before, merge("x", "y").config, g)).toBeNull();
    expect(mergeKeyRename(before, merge("a", "b").config, g)).toBeNull();
  });

  it("carries nothing for a blank or repeated name, or a branch that changed wire", () => {
    const before = merge("a", "b");
    const g = graphOf(before);
    expect(mergeKeyRename(before, merge("a", "").config, g)).toBeNull();
    expect(mergeKeyRename(before, merge("a", "a").config, g)).toBeNull();
    const moved = merge("a", "c");
    (moved.config.branch_keys as { source_port: string }[])[1]!.source_port = "other";
    expect(mergeKeyRename(before, moved.config, g)).toBeNull();
  });

  it("tolerates entries that are not objects", () => {
    const before = { ...merge("a"), config: { branch_keys: ["junk"] } };
    expect(mergeKeyRename(before, merge("x").config, graphOf(before))).toBeNull();
  });

  it("continues a rename from the one name still read after the old one was cleared", () => {
    const before = merge("a", "");
    const g = graphOf(before, read("a"), read("research"));
    expect(mergeKeyRename(before, merge("a", "r").config, g)).toEqual({
      from: "research",
      to: "r",
    });
    // Two names are read and neither is a key: nothing says which one was meant.
    const two = graphOf(before, read("one"), read("two"));
    expect(mergeKeyRename(before, merge("a", "r").config, two)).toBeNull();
    // A read of another step's branches is not this merge's.
    expect(
      mergeKeyRename(before, merge("a", "r").config, graphOf(before, read("x", "other"))),
    ).toBeNull();
  });
});

describe("mergeKeyRename by wire", () => {
  const entry = (wire: string, key: string) => ({
    source_node_id: wire,
    source_port: "out",
    key,
  });
  const unstored = { ...merge(), config: { wait_for: "all" } };

  it("matches entries by the wire they name when a leg was deleted", () => {
    const before = merge("a", "b", "c");
    const after = { wait_for: "all", branch_keys: [entry("s0", "a"), entry("s2", "z")] };
    expect(mergeKeyRename(before, after, graphOf(before))).toEqual({ from: "c", to: "z" });
  });

  it("refuses a name another branch has, after a deleted leg too", () => {
    const before = merge("a", "b", "c");
    const after = { wait_for: "all", branch_keys: [entry("s0", "a"), entry("s2", "a")] };
    expect(mergeKeyRename(before, after, graphOf(before))).toBeNull();
  });

  it("carries the first rename of a merge whose names were never stored", () => {
    const after = { wait_for: "all", branch_keys: [entry("s0", "sources"), entry("s1", "draft")] };
    const g = graphOf(unstored, read("research"), read("draft"));
    expect(mergeKeyRename(unstored, after, g)).toEqual({ from: "research", to: "sources" });
  });

  it("carries nothing when it cannot tell which default was renamed", () => {
    const after = { wait_for: "all", branch_keys: [entry("s0", "sources"), entry("s1", "draft")] };
    // `draft` is unread too, so either new name could be the renamed one.
    expect(mergeKeyRename(unstored, after, graphOf(unstored, read("research")))).toBeNull();
    // Two names are read and neither is a branch's now.
    expect(
      mergeKeyRename(unstored, after, graphOf(unstored, read("research"), read("old"))),
    ).toBeNull();
  });

  it("carries nothing for an edit that also changes the mode", () => {
    const after = { wait_for: "one", branch_keys: [entry("s0", "sources"), entry("s1", "draft")] };
    const g = graphOf(unstored, read("research"), read("draft"));
    expect(mergeKeyRename(unstored, after, g)).toBeNull();
  });

  it("carries nothing without a list of names", () => {
    expect(mergeKeyRename(unstored, { wait_for: "all" }, graphOf(unstored))).toBeNull();
  });
});

describe("carryMergeKeyRename", () => {
  const rename = { from: "a", to: "z" };

  it("rewrites bindings and template parts that read the branch, whole or by field", () => {
    const before = merge("a");
    const g = graphOf(
      before,
      read("a"),
      read("other"),
      read("a", "elsewhere"),
      { target_node_id: "t", target_field: "lit", source: { kind: "literal", value: 1 } },
      {
        target_node_id: "t",
        target_field: "tpl",
        source: {
          kind: "template",
          parts: [
            "x",
            {
              kind: "node_output",
              node_id: "m",
              port: "value",
              field_path: ["branches", "a", "q"],
            },
          ],
        },
      },
      {
        target_node_id: "t",
        target_field: "tpl2",
        source: { kind: "template", parts: ["no reads"] },
      },
    );
    const carried = carryMergeKeyRename(g, "m", rename).bindings;
    expect(carried[0]?.source).toMatchObject({ field_path: ["branches", "z"] });
    expect(carried[1]).toBe(g.bindings[1]);
    expect(carried[2]).toBe(g.bindings[2]);
    expect(carried[3]).toBe(g.bindings[3]);
    expect(carried[4]?.source).toMatchObject({
      parts: ["x", { field_path: ["branches", "z", "q"] }],
    });
    expect(carried[5]).toBe(g.bindings[5]);
  });
});
