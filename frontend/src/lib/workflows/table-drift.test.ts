import { describe, expect, it } from "vitest";

import {
  graphTableRefs,
  orphanValueBindings,
  rebindRef,
  recordWriterTables,
  safeToRebind,
  withRebound,
} from "./table-drift";
import type { TableIORef, WorkflowGraph } from "./types";
import type { ColumnDef, SchemaVersionRead, TableRead } from "@/types/tables";

function column(id: string, type = "text", archived = false): ColumnDef {
  return { id, label: id, type, archived } as ColumnDef;
}

function ref(column_ids: string[] | null, schema_version = 1): TableIORef {
  return { kind: "table", table_id: "t1", column_ids, schema_version };
}

function table(columns: ColumnDef[], schema_version = 2): TableRead {
  return { id: "t1", schema_version, columns } as TableRead;
}

function versions(columns: ColumnDef[]): SchemaVersionRead[] {
  return [{ version: 1, columns, created_by: null, created_at: "2026-11-01T00:00:00Z" }];
}

const GRAPH = {
  entry_node_id: "a",
  nodes: [
    { id: "a", definition_id: "table.read", definition_version: 1, config: { table: ref(["c1"]) } },
    { id: "b", definition_id: "agent", definition_version: 1, config: { table: "not a ref" } },
  ],
  edges: [],
  bindings: [
    { target_node_id: "b", target_field: "rows", source: ref(null) },
    { target_node_id: "b", target_field: "x", source: { kind: "literal", value: 1 } },
  ],
  scopes: [],
} as unknown as WorkflowGraph;

describe("graphTableRefs", () => {
  it("finds a step's own table and every table-sourced binding, and nothing else", () => {
    expect(graphTableRefs(GRAPH)).toEqual([
      { site: { nodeId: "a", binding: null }, ref: ref(["c1"]) },
      { site: { nodeId: "b", binding: 0 }, ref: ref(null) },
    ]);
  });
});

describe("safeToRebind", () => {
  it("accepts a schema that only added columns", () => {
    const bound = [column("c1"), column("c2")];
    expect(safeToRebind(ref(["c1"]), table([...bound, column("c3")]), versions(bound))).toBe(true);
    expect(safeToRebind(ref(null), table([...bound, column("c3")]), versions(bound))).toBe(true);
  });

  it("accepts a change to a column the reference does not read", () => {
    const bound = [column("c1"), column("c2")];
    expect(safeToRebind(ref(["c1"]), table([column("c1")]), versions(bound))).toBe(true);
  });

  it("refuses a read column removed, archived or retyped", () => {
    const bound = [column("c1"), column("c2")];
    expect(safeToRebind(ref(["c2"]), table([column("c1")]), versions(bound))).toBe(false);
    expect(
      safeToRebind(ref(["c2"]), table([column("c1"), column("c2", "text", true)]), versions(bound)),
    ).toBe(false);
    expect(
      safeToRebind(ref(["c2"]), table([column("c1"), column("c2", "number")]), versions(bound)),
    ).toBe(false);
  });

  it("refuses, for an all-columns reference, any column it had that is gone", () => {
    const bound = [column("c1"), column("c2"), column("old", "text", true)];
    expect(safeToRebind(ref(null), table([column("c1")]), versions(bound))).toBe(false);
    // An archived column was never read, so its absence changes nothing.
    expect(safeToRebind(ref(null), table([column("c1"), column("c2")]), versions(bound))).toBe(
      true,
    );
  });

  it("refuses when the bound version is not in the history", () => {
    expect(safeToRebind(ref(["c1"], 7), table([column("c1")]), versions([column("c1")]))).toBe(
      false,
    );
  });
});

describe("rebindRef", () => {
  it("keeps the chosen columns that still exist", () => {
    expect(rebindRef(ref(["c1", "gone"]), 2, [column("c1")])).toEqual(ref(["c1"], 2));
  });

  it("falls back to all columns when none of the chosen ones survived", () => {
    expect(rebindRef(ref(["gone"]), 2, [column("c1")])).toEqual(ref(null, 2));
    expect(rebindRef(ref(null), 2, [column("c1")])).toEqual(ref(null, 2));
  });
});

describe("withRebound", () => {
  it("replaces each named site's reference and leaves the rest", () => {
    const next = withRebound(GRAPH, [
      { site: { nodeId: "a", binding: null }, ref: ref(["c1"], 2) },
      { site: { nodeId: "b", binding: 0 }, ref: ref(null, 2) },
    ]);
    expect(next.nodes[0]!.config).toEqual({ table: ref(["c1"], 2) });
    expect(next.nodes[1]).toBe(GRAPH.nodes[1]);
    expect(next.bindings[0]!.source).toEqual(ref(null, 2));
    expect(next.bindings[1]).toBe(GRAPH.bindings[1]);
  });
});

describe("orphanValueBindings", () => {
  const writer = {
    entry_node_id: "w",
    nodes: [
      {
        id: "w",
        definition_id: "table.record.update",
        definition_version: 1,
        config: { table: ref(null, 2) },
      },
      {
        id: "r",
        definition_id: "table.record.get",
        definition_version: 1,
        config: { table: ref(null, 2) },
      },
    ],
    edges: [],
    bindings: [
      { target_node_id: "w", target_field: "values/c1", source: { kind: "literal", value: 1 } },
      { target_node_id: "w", target_field: "values/gone", source: { kind: "literal", value: 1 } },
      { target_node_id: "r", target_field: "values/gone", source: { kind: "literal", value: 1 } },
    ],
    scopes: [],
  } as unknown as WorkflowGraph;

  it("names a writer's value bound to a column no longer live, and nothing else", () => {
    expect(orphanValueBindings(writer, new Map([["t1", new Set(["c1"])]]))).toEqual([
      { nodeId: "w", field: "values/gone" },
    ]);
  });

  it("leaves a writer whose table's columns are not known", () => {
    expect(orphanValueBindings(writer, new Map())).toEqual([]);
  });

  it("lists only writers that bind per-column values", () => {
    expect(recordWriterTables(writer)).toEqual([{ tableId: "t1", version: 2 }]);
    expect(recordWriterTables(GRAPH)).toEqual([]);
  });
});
