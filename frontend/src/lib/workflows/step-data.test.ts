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
  isInsideALoop,
  jsonBytes,
  knownInput,
  knownOutputs,
  schemaOf,
  sourcesOf,
  stepDataOf,
  tableOf,
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
          entry_port: "body",
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
