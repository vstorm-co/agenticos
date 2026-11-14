import { describe, expect, it } from "vitest";

import {
  edge,
  graph,
  literalBinding,
  node,
  nodeOutputBinding,
} from "@/components/workflows/validation/fixtures";

import {
  ancestorsOf,
  cellText,
  earlierSteps,
  isInsideALoop,
  iterationDataOf,
  iterationOf,
  jsonBytes,
  knownInput,
  knownOutputs,
  schemaOf,
  sourcesOf,
  stepDataAt,
  stepDataOf,
  stepsTaken,
  tableOf,
  testEntryGraph,
} from "./step-data";
import type { WorkflowNodeRunRead } from "./types";

function row(overrides: Partial<WorkflowNodeRunRead>): WorkflowNodeRunRead {
  return {
    id: crypto.randomUUID(),
    node_instance_id: "a",
    scope_path: [],
    status: "succeeded",
    waiting_reason: null,
    attempts: 1,
    cost: 0,
    error: null,
    output: null,
    last_attempt_status: null,
    late_output: null,
    started_at: null,
    ended_at: null,
    ...overrides,
  };
}

const LINE = graph({
  entry: "a",
  nodes: [node("a", "core.input"), node("b", "data.map"), node("c", "core.output")],
  edges: [edge("e1", "a", "out", "b", "in"), edge("e2", "b", "out", "c", "in")],
  bindings: [
    nodeOutputBinding("c", "text", "a", "out", ["payload"]),
    literalBinding("c", "note", "x"),
  ],
});

describe("what a run's steps did", () => {
  it("keeps each step's output or error, the last loop item winning", () => {
    const data = stepDataOf("r", [
      row({ node_instance_id: "a", output: { n: 1 } }),
      row({ node_instance_id: "a", output: { n: 2 } }),
      row({ node_instance_id: "b", status: "failed", error: { code: "BAD", message: "No" } }),
      row({ node_instance_id: "c", status: "running" }),
      row({ node_instance_id: "d", status: "failed" }),
    ]);

    expect(data).toEqual({
      a: { output: { n: 2 }, error: null, runId: "r" },
      b: { output: null, error: { code: "BAD", message: "No" }, runId: "r" },
    });
  });
});

describe("how a run's approval steps were decided", () => {
  it("keeps an approval when dispatch fails after the decision", () => {
    const approval = { status: "approved" as const, decided_at: null, decided_by_name: "Ola" };
    const error = { code: "PRINCIPAL_REVOKED", message: "Access was revoked" };
    const data = stepDataOf("r", [row({ status: "failed", error, approval })]);
    expect(data.a).toEqual({ output: null, error, runId: "r", approval });
  });

  it("keeps the decision with the step's output, and adds nothing to other steps", () => {
    const approval = {
      status: "approved" as const,
      decided_at: "2026-11-13T10:28:00Z",
      decided_by_name: "Ola",
    };
    const data = stepDataOf("r", [
      row({ node_instance_id: "a", output: { decision: "approved" }, approval }),
      row({ node_instance_id: "b", output: { n: 1 }, approval: null }),
    ]);

    expect(data.a).toEqual({ output: { decision: "approved" }, error: null, runId: "r", approval });
    expect(data.b).toEqual({ output: { n: 1 }, error: null, runId: "r" });
  });

  it("keeps a request its run was cancelled during, with nothing handed on", () => {
    const approval = { status: "cancelled" as const, decided_at: null, decided_by_name: null };
    const data = stepDataOf("r", [
      row({ node_instance_id: "a", status: "cancelled", approval }),
      row({ node_instance_id: "b", status: "cancelled" }),
    ]);

    expect(data).toEqual({ a: { output: null, error: null, runId: "r", approval } });
  });
});

describe("what a run's steps did in each loop iteration", () => {
  const loop = (index: number) => [{ loop_node_id: "l", index }];
  const rows = [
    row({ node_instance_id: "t", output: { list: [1, 2] } }),
    row({ node_instance_id: "i", scope_path: loop(0), output: { item: 1 } }),
    row({ node_instance_id: "h", scope_path: loop(0), output: { got: 1 } }),
    row({ node_instance_id: "i", scope_path: loop(1), output: { item: 2 } }),
    row({ node_instance_id: "h", scope_path: loop(1), status: "running" }),
  ];
  const latest = stepDataOf("r", rows);
  const iterations = iterationDataOf("r", rows);

  it("names a row's iteration by its index in each loop around it", () => {
    expect(iterationOf(row({ scope_path: [] }))).toEqual([]);
    expect(
      iterationOf(
        row({
          scope_path: [
            { loop_node_id: "l", index: 1 },
            { loop_node_id: "m", index: 3 },
          ],
        }),
      ),
    ).toEqual([1, 3]);
  });

  it("reads each step as it was in the iteration asked for, not the last one", () => {
    expect(stepDataAt(latest, iterations, "i", [0])?.output).toEqual({ item: 1 });
    expect(stepDataAt(latest, iterations, "h", [0])?.output).toEqual({ got: 1 });
    expect(stepDataAt(latest, iterations, "i", [1])?.output).toEqual({ item: 2 });
  });

  it("reads a step outside the loop as its latest", () => {
    expect(stepDataAt(latest, iterations, "t", [1])?.output).toEqual({ list: [1, 2] });
    expect(stepDataAt(latest, iterations, "i", [])?.output).toEqual({ item: 2 });
    expect(stepDataAt(latest, iterations, "missing", [0])).toBeUndefined();
  });

  it("reads a step still running in that iteration as empty, never another iteration's", () => {
    expect(stepDataAt(latest, iterations, "h", [1])).toEqual({
      output: null,
      error: null,
      runId: "r",
    });
  });

  it.each(["pending", "running", "cancelled", "skipped"] as const)(
    "does not borrow the previous iteration's output for a %s step",
    (status) => {
      const scoped = iterationDataOf("r", [
        row({ node_instance_id: "h", scope_path: loop(0), output: { got: 1 } }),
        row({ node_instance_id: "h", scope_path: loop(1), status }),
      ]);
      expect(stepDataAt(latest, scoped, "h", [1])).toEqual({
        output: null,
        error: null,
        runId: "r",
      });
    },
  );

  it("reads a source from the nearest enclosing iteration", () => {
    const scoped = iterationDataOf("r", [
      row({ node_instance_id: "i", scope_path: loop(0), output: { item: 1 } }),
      row({ node_instance_id: "i", scope_path: loop(1), output: { item: 2 } }),
    ]);
    expect(stepDataAt(latest, scoped, "i", [0, 3])?.output).toEqual({ item: 1 });
  });
});

describe("the steps a run took", () => {
  it("keeps the server's sub-millisecond start order", () => {
    const rows = [
      row({ id: "http", started_at: "2026-11-10T10:00:00.123900Z" }),
      row({ id: "item", started_at: "2026-11-10T10:00:00.123100Z" }),
      row({ id: "result", started_at: "2026-11-10T10:00:00.124000Z" }),
    ];
    expect(stepsTaken(rows).map((taken) => taken.id)).toEqual(["item", "http", "result"]);
    expect(rows.map((taken) => taken.id)).toEqual(["http", "item", "result"]);
  });

  it("compares equivalent timestamp formats without losing their stable order", () => {
    const rows = [
      row({ id: "later", started_at: "2026-11-10T10:00:00.123900Z" }),
      row({ id: "offset", started_at: "2026-11-10T11:00:00.1231+01:00" }),
      row({ id: "utc", started_at: "2026-11-10T10:00:00.123100Z" }),
    ];
    expect(stepsTaken(rows).map((taken) => taken.id)).toEqual(["offset", "utc", "later"]);
  });

  it("lists the steps that started, in the order they started", () => {
    const at = (second: number) => `2026-11-10T10:00:0${second}Z`;
    const rows = [
      row({ id: "http", started_at: at(2) }),
      row({ id: "item", started_at: at(1), ended_at: at(1) }),
      row({ id: "failed", status: "failed", ended_at: at(3) }),
      row({ id: "unsettled", status: "failed" }),
      row({ id: "next", status: "pending" }),
      row({ id: "skipped", status: "skipped", ended_at: at(4) }),
      row({ id: "cancelled", status: "cancelled", ended_at: at(4) }),
      row({ id: "retrying", status: "pending", started_at: at(0) }),
    ];

    expect(stepsTaken(rows).map((taken) => taken.id)).toEqual([
      "retrying",
      "item",
      "http",
      "failed",
      "unsettled",
    ]);
  });
});

describe("the steps around a step", () => {
  it("reads from what it is bound to and wired from, in the graph's order", () => {
    expect(sourcesOf(LINE, "c")).toEqual(["a", "b"]);
    expect(sourcesOf(LINE, "a")).toEqual([]);
  });

  it("finds everything that leads to a step", () => {
    expect([...ancestorsOf(LINE, "c")].sort()).toEqual(["a", "b"]);
    expect(ancestorsOf(LINE, "a").size).toBe(0);
  });

  it("knows a step inside a loop", () => {
    const looped = {
      ...LINE,
      scopes: [
        {
          scope_node_id: "b",
          body_node_ids: ["c"],
          exit_node_id: "b",
          exit_port: "done",
        },
      ],
    };
    expect(isInsideALoop(looped, "c")).toBe(true);
    expect(isInsideALoop(looped, "b")).toBe(false);
  });

  it("pins what the steps before a step handed on, and reads the run's input off the trigger", () => {
    const data = {
      a: { output: { payload: { name: "Ada" } }, error: null, runId: "r" },
      b: { output: null, error: { code: "BAD", message: "No" }, runId: "r" },
      c: { output: { text: "done" }, error: null, runId: "r" },
    };

    expect(knownOutputs(LINE, "c", data)).toEqual({ a: { payload: { name: "Ada" } } });
    expect(knownInput(LINE, data)).toEqual({ name: "Ada" });
    expect(knownInput(LINE, {})).toBeNull();
    expect(
      knownInput(LINE, { a: { output: { payload: "text" }, error: null, runId: "r" } }),
    ).toBeNull();
  });
});

describe("data as a table", () => {
  it("shows a list of records as its rows, which no single path reaches", () => {
    const table = tableOf({ total: 2, records: [{ id: 1 }, { id: 2, name: "B" }] });
    expect(table).toEqual({
      columns: ["id", "name"],
      rows: [{ id: 1 }, { id: 2, name: "B" }],
      paths: null,
    });
  });

  it("shows anything else as one row, nested objects spread into columns with their paths", () => {
    const table = tableOf({ payload: { name: "Ada", deep: { x: 1 } }, by: "api", tags: [] });
    expect(table.columns).toEqual(["payload.name", "payload.deep", "by", "tags"]);
    expect(table.rows[0]?.["payload.deep"]).toEqual({ x: 1 });
    expect(table.paths?.["payload.name"]).toEqual(["payload", "name"]);
  });

  it("shows a table's fields in its column order, which the stored data loses", () => {
    // Postgres hands back an object's keys shortest first.
    const record = { fields: { Notes: "n", Score: 1, Company: "Acme" }, record_id: "r" };
    const table = tableOf({ records: [record] }, ["Company", "Score", "Notes"]);
    expect(table.columns).toEqual(["fields.Company", "fields.Score", "fields.Notes", "record_id"]);
  });

  it("keeps the order a column came in when no order is given", () => {
    expect(tableOf({ a: 1, p: { x: 1 }, b: 2 }).columns).toEqual(["a", "p.x", "b"]);
  });

  it("shows at most twelve columns", () => {
    const wide = Object.fromEntries(Array.from({ length: 20 }, (_, index) => [`c${index}`, index]));
    expect(tableOf(wide).columns).toHaveLength(12);
  });

  it("writes a cell as short text", () => {
    expect(cellText(undefined)).toBe("");
    expect(cellText("plain")).toBe("plain");
    expect(cellText(3)).toBe("3");
    expect(cellText({ long: "x".repeat(100) })).toHaveLength(80);
  });
});

describe("data as its fields", () => {
  it("lists each field by path with its type, into objects and lists of objects", () => {
    expect(schemaOf({ a: null, b: { c: "x" }, d: [{ e: 1 }], f: [1] })).toEqual([
      { path: "a", type: "null", segments: ["a"] },
      { path: "b", type: "object", segments: ["b"] },
      { path: "b.c", type: "string", segments: ["b", "c"] },
      { path: "d", type: "array", segments: ["d"] },
      { path: "d[].e", type: "number", segments: null },
      { path: "f", type: "array", segments: ["f"] },
    ]);
  });

  it("stops four levels down and at two hundred fields", () => {
    const deep = { a: { b: { c: { d: { e: 1 } } } } };
    expect(schemaOf(deep).map((field) => field.path)).toEqual(["a", "a.b", "a.b.c", "a.b.c.d"]);
    const many = Object.fromEntries(
      Array.from({ length: 150 }, (_, index) => [`k${index}`, { v: 1 }]),
    );
    expect(schemaOf(many)).toHaveLength(200);
  });

  it("measures data as the service does", () => {
    expect(jsonBytes({ a: "é" })).toBe(10);
  });
});

describe("earlierSteps", () => {
  const wire = (id: string, from: string, to: string) => ({
    id,
    source_node_id: from,
    source_port: "out",
    target_node_id: to,
    target_port: "in",
  });
  const graph = {
    entry_node_id: "a",
    nodes: ["a", "b", "x", "c", "far"].map((id) => ({
      id,
      definition_id: "t",
      definition_version: 1,
      config: {},
      layout: { x: 0, y: 0 },
    })),
    edges: [wire("1", "a", "b"), wire("2", "b", "c"), wire("3", "x", "c")],
    bindings: [
      {
        target_node_id: "c",
        target_field: "v",
        source: { kind: "node_output" as const, node_id: "far", port: "out", field_path: [] },
      },
    ],
    scopes: [],
  };

  it("puts the steps just before first, then further back, then ones it reads unwired", () => {
    expect(earlierSteps(graph, "c", new Set(["a", "b"]))).toEqual(["b", "x", "a", "far"]);
  });

  it("never offers the step itself, and has nothing before the first step", () => {
    expect(earlierSteps(graph, "c", new Set(["c"]))).not.toContain("c");
    expect(earlierSteps(graph, "a", new Set())).toEqual([]);
  });

  it("never offers a step switched off, even the one wired just before", () => {
    const off = {
      ...graph,
      nodes: graph.nodes.map((node) => (node.id === "b" ? { ...node, disabled: true } : node)),
    };
    expect(earlierSteps(off, "c", new Set(["a", "b"]))).toEqual(["x", "a", "far"]);
  });
});

describe("testEntryGraph", () => {
  it("returns the default entry's branch when it reaches the step", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("c", "data.map")],
      edges: [edge("e", "a", "out", "c", "in")],
    });

    expect(testEntryGraph(g, "c")?.entry_node_id).toBe("a");
    expect(testEntryGraph(g, "c")?.nodes.map((n) => n.id)).toEqual(["a", "c"]);
  });

  it("picks the secondary trigger whose branch reaches the step, default first", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("b", "trigger.manual"), node("c", "data.map")],
      edges: [edge("e", "b", "out", "c", "in")],
    });

    expect(testEntryGraph(g, "c")?.entry_node_id).toBe("b");
    expect(testEntryGraph(g, "c")?.nodes.map((n) => n.id)).toEqual(["b", "c"]);
  });

  it("keeps the default entry when several starts reach the step", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("b", "trigger.manual"), node("c", "data.map")],
      edges: [edge("e1", "a", "out", "c", "in"), edge("e2", "b", "out", "c", "in")],
    });

    expect(testEntryGraph(g, "c")?.entry_node_id).toBe("a");
  });

  it("returns null when no entry reaches the step", () => {
    const g = graph({
      entry: "a",
      nodes: [node("a", "trigger.manual"), node("c", "data.map")],
      edges: [],
    });

    expect(testEntryGraph(g, "c")).toBeNull();
  });
});
