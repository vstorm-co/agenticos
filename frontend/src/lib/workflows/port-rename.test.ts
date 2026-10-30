import { describe, expect, it } from "vitest";

import { carryPortRename, portRename } from "./port-rename";
import type { NodeInstance, WorkflowGraph } from "./types";

const EMPTY: WorkflowGraph = { entry_node_id: "s", nodes: [], edges: [], bindings: [], scopes: [] };

const sw = (rules: unknown[], extra: Partial<NodeInstance> = {}): NodeInstance => ({
  id: "s",
  definition_id: "logic.switch",
  definition_version: 1,
  config: { rules },
  layout: { x: 0, y: 0 },
  ...extra,
});

describe("portRename", () => {
  it("names the one entry whose name changed", () => {
    expect(
      portRename(
        sw([{ name: "big" }, { name: "small" }]),
        {
          rules: [{ name: "large" }, { name: "small" }],
        },
        EMPTY,
      ),
    ).toEqual({ from: "big", to: "large" });
  });

  it.each([
    ["a reorder", [{ name: "a" }, { name: "b" }], [{ name: "b" }, { name: "a" }]],
    ["an insert", [{ name: "a" }], [{ name: "a" }, { name: "b" }]],
    ["a delete", [{ name: "a" }, { name: "b" }], [{ name: "a" }]],
    ["two changes", [{ name: "a" }, { name: "b" }], [{ name: "c" }, { name: "d" }]],
    ["an old name used twice", [{ name: "a" }, { name: "a" }], [{ name: "c" }, { name: "a" }]],
    ["a new name another rule has", [{ name: "a" }, { name: "b" }], [{ name: "b" }, { name: "b" }]],
    ["a static port", [{ name: "a" }], [{ name: "otherwise" }]],
    ["a blank name", [{ name: "a" }], [{ name: "" }]],
    ["a name that was not text", [{ name: 1 }], [{ name: "a" }]],
    ["an entry that is not an object", [null], [{ name: "a" }]],
  ])("carries nothing for %s", (_case, before, after) => {
    expect(portRename(sw(before), { rules: after }, EMPTY)).toBeNull();
  });

  it("refuses `error` on a step that routes errors, and `unsure` on a classifier with a minimum", () => {
    const routed = sw([{ name: "a" }], { policy: { on_error: "route" } });
    expect(portRename(routed, { rules: [{ name: "error" }] }, EMPTY)).toBeNull();
    const plain = sw([{ name: "a" }]);
    expect(portRename(plain, { rules: [{ name: "error" }] }, EMPTY)).toEqual({
      from: "a",
      to: "error",
    });
    const classify: NodeInstance = {
      id: "c",
      definition_id: "ai.classify",
      definition_version: 1,
      config: { categories: [{ name: "a" }], min_confidence: 0.5 },
      layout: { x: 0, y: 0 },
    };
    expect(
      portRename(classify, { categories: [{ name: "unsure" }], min_confidence: 0.5 }, EMPTY),
    ).toBeNull();
    expect(
      portRename(
        { ...classify, config: { categories: [{ name: "a" }] } },
        {
          categories: [{ name: "unsure" }],
        },
        EMPTY,
      ),
    ).toEqual({ from: "a", to: "unsure" });
  });

  it("reads approval choices by id, and error branches and categories by name", () => {
    const approval: NodeInstance = {
      id: "h",
      definition_id: "human.approval",
      definition_version: 1,
      config: { choices: [{ id: "yes", label: "Yes" }] },
      layout: { x: 0, y: 0 },
    };
    expect(portRename(approval, { choices: [{ id: "ok", label: "Yes" }] }, EMPTY)).toEqual({
      from: "yes",
      to: "ok",
    });
    expect(portRename(approval, { choices: [{ id: "yes", label: "Sure" }] }, EMPTY)).toBeNull();
    const handler: NodeInstance = {
      id: "e",
      definition_id: "error.handle",
      definition_version: 1,
      config: { branches: [{ name: "x" }] },
      layout: { x: 0, y: 0 },
    };
    expect(portRename(handler, { branches: [{ name: "y" }] }, EMPTY)).toEqual({
      from: "x",
      to: "y",
    });
  });

  it("carries nothing for a step without author-named ports, or a list that is not one", () => {
    const echo: NodeInstance = { ...sw([]), definition_id: "debug.echo" };
    expect(portRename(echo, { rules: [{ name: "a" }] }, EMPTY)).toBeNull();
    expect(portRename(sw([{ name: "a" }]), { rules: "nope" }, EMPTY)).toBeNull();
    expect(portRename({ ...sw([]), config: {} }, { rules: [{ name: "a" }] }, EMPTY)).toBeNull();
  });
});

describe("portRename after a name was cleared or passed through a duplicate", () => {
  const wired = (port: string): WorkflowGraph => ({
    ...EMPTY,
    nodes: [sw([])],
    edges: [
      { id: "e", source_node_id: "s", source_port: port, target_node_id: "t", target_port: "in" },
    ],
  });

  it("continues from the port still wired when the old name is blank", () => {
    expect(portRename(sw([{ name: "" }]), { rules: [{ name: "l" }] }, wired("b"))).toEqual({
      from: "b",
      to: "l",
    });
    expect(portRename(sw([{}]), { rules: [{ name: "l" }] }, wired("b"))).toEqual({
      from: "b",
      to: "l",
    });
  });

  it("continues from the port still wired when the old name is another rule's too", () => {
    expect(
      portRename(
        sw([{ name: "ab" }, { name: "ab" }]),
        { rules: [{ name: "abc" }, { name: "ab" }] },
        wired("a"),
      ),
    ).toEqual({ from: "a", to: "abc" });
  });

  it("carries nothing when no port, or several, are orphaned, or the port is a live one", () => {
    expect(portRename(sw([{ name: "" }]), { rules: [{ name: "l" }] }, EMPTY)).toBeNull();
    const two = wired("b");
    two.edges.push({ ...two.edges[0]!, id: "f", source_port: "c" });
    expect(portRename(sw([{ name: "" }]), { rules: [{ name: "l" }] }, two)).toBeNull();
    expect(
      portRename(sw([{ name: "" }]), { rules: [{ name: "l" }] }, wired("otherwise")),
    ).toBeNull();
  });

  it("reads bindings, template parts and the quick log as references too", () => {
    const g: WorkflowGraph = {
      ...EMPTY,
      nodes: [sw([], { quick_log: { message: "m", outputs: ["b"] } })],
      bindings: [
        {
          target_node_id: "t",
          target_field: "x",
          source: { kind: "node_output", node_id: "s", port: "b", field_path: [] },
        },
        {
          target_node_id: "t",
          target_field: "y",
          source: {
            kind: "template",
            parts: ["x", { kind: "node_output", node_id: "s", port: "b", field_path: [] }],
          },
        },
        {
          target_node_id: "t",
          target_field: "z",
          source: { kind: "node_output", node_id: "other", port: "q", field_path: [] },
        },
        { target_node_id: "t", target_field: "w", source: { kind: "literal", value: 1 } },
      ],
    };
    expect(portRename(sw([{ name: "" }]), { rules: [{ name: "l" }] }, g)).toEqual({
      from: "b",
      to: "l",
    });
  });
});

describe("carryPortRename", () => {
  const graph = (): WorkflowGraph => ({
    entry_node_id: "s",
    nodes: [
      sw([{ name: "big" }], { quick_log: { message: "m", outputs: ["big", "otherwise"] } }),
      { ...sw([{ name: "big" }]), id: "t", quick_log: { message: "m", outputs: ["big"] } },
      { ...sw([]), id: "a", definition_id: "debug.echo", config: {} },
      { ...sw([]), id: "d", definition_id: "debug.echo", config: {} },
      { ...sw([]), id: "b", definition_id: "debug.echo", config: {} },
      { ...sw([]), id: "c", definition_id: "debug.echo", config: {} },
    ],
    edges: [
      { id: "e1", source_node_id: "s", source_port: "big", target_node_id: "a", target_port: "in" },
      { id: "e2", source_node_id: "t", source_port: "big", target_node_id: "d", target_port: "in" },
      {
        id: "e3",
        source_node_id: "s",
        source_port: "otherwise",
        target_node_id: "b",
        target_port: "in",
      },
    ],
    bindings: [
      {
        target_node_id: "b",
        target_field: "message",
        source: { kind: "node_output", node_id: "s", port: "big", field_path: ["value"] },
      },
      {
        target_node_id: "c",
        target_field: "text",
        source: {
          kind: "template",
          parts: ["x", { kind: "node_output", node_id: "s", port: "big", field_path: [] }],
        },
      },
      {
        target_node_id: "c",
        target_field: "other",
        source: { kind: "node_output", node_id: "t", port: "big", field_path: [] },
      },
      {
        target_node_id: "c",
        target_field: "lit",
        source: { kind: "literal", value: 1 },
      },
    ],
    scopes: [],
  });

  it("moves the step's edges, bindings, template references and quick log to the new name", () => {
    const carried = carryPortRename(graph(), "s", { from: "big", to: "large" });
    expect(carried.edges.map((e) => e.source_port)).toEqual(["large", "big", "otherwise"]);
    const first = carried.bindings[0]?.source;
    expect(first?.kind === "node_output" && first.port).toBe("large");
    const template = carried.bindings[1]?.source;
    expect(
      template?.kind === "template" &&
        template.parts.map((part) => (typeof part === "string" ? part : part.port)),
    ).toEqual(["x", "large"]);
    const other = carried.bindings[2]?.source;
    expect(other?.kind === "node_output" && other.port).toBe("big");
    expect(carried.bindings[3]).toEqual(graph().bindings[3]);
    expect(carried.nodes.find((n) => n.id === "s")?.quick_log?.outputs).toEqual([
      "large",
      "otherwise",
    ]);
    expect(carried.nodes.find((n) => n.id === "t")?.quick_log?.outputs).toEqual(["big"]);
  });

  it("changes nothing when nothing reads the old name", () => {
    const g = graph();
    expect(carryPortRename(g, "s", { from: "none", to: "x" })).toEqual(g);
  });

  it("leaves a step whose quick log logs every outcome alone", () => {
    const g = graph();
    g.nodes[0] = sw([{ name: "big" }], { quick_log: { message: "m", outputs: null } });
    const carried = carryPortRename(g, "s", { from: "big", to: "large" });
    expect(carried.nodes[0]?.quick_log?.outputs).toBeNull();
  });
});
