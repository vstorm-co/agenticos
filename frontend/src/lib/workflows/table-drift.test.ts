import { describe, expect, it } from "vitest";

import {
  graphTableRefs,
  nodeTableColumns,
  isTableRefusalField,
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
  it("leaves switched-off steps and their incoming table bindings untouched", () => {
    const disabled = { ...GRAPH, nodes: GRAPH.nodes.map((node) => ({ ...node, disabled: true })) };
    expect(graphTableRefs(disabled)).toEqual([]);
    expect(nodeTableColumns(disabled, { nodeId: "a", binding: null })).toEqual([]);
    expect(graphTableRefs(GRAPH)).toHaveLength(2);
  });
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

  it("refuses a read column whose meaning changed under the same type", () => {
    // A formula, a lookup or an option changed: `revision` moved, the type did not.
    const bound = [{ ...column("c1"), revision: 1 }];
    const now = [{ ...column("c1"), revision: 2 }];
    expect(safeToRebind(ref(["c1"]), table(now), versions(bound))).toBe(false);
    expect(safeToRebind(ref(["c1"]), table(bound), versions(bound))).toBe(true);
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

  it("keeps an emptied choice empty, rather than widening it to every column", () => {
    expect(rebindRef(ref(["gone"]), 2, [column("c1")])).toEqual(ref([], 2));
  });

  it("keeps an all-columns reference all columns", () => {
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
    const live = new Map([["t1", { version: 2, columns: [{ id: "c1", label: "Score" }] }]]);
    expect(orphanValueBindings(writer, live)).toEqual([{ nodeId: "w", field: "values/gone" }]);
  });

  it("leaves a writer still on an older schema to its author", () => {
    // The same table, but this step was bound at version 1: its drift is pending.
    const live = new Map([["t1", { version: 3, columns: [{ id: "c1", label: "Score" }] }]]);
    expect(orphanValueBindings(writer, live)).toEqual([]);
  });

  it.each([
    ["Score", "Score"],
    ["sCoRe", "Score"],
    ["Score~1Delta", "Score/Delta"],
    ["Cost~0gross", "Cost~gross"],
    ["Cost~01gross", "Cost~1gross"],
    ["STRASSE", "Straße"],
    ["SS", "ẞ"],
    ["Ꭰ", "ꭰ"],
    ["σ", "ς"],
    ["𐐀", "𐐨"],
  ])("preserves the live label binding %s", (field, label) => {
    const graph = {
      ...writer,
      bindings: [{ ...writer.bindings[0]!, target_field: `values/${field}` }],
    };
    const live = new Map([["t1", { version: 2, columns: [{ id: "c1", label }] }]]);
    expect(orphanValueBindings(graph, live)).toEqual([]);
  });

  it("drops an i binding for a dotless-i column, as the server treats them as distinct", () => {
    const graph = { ...writer, bindings: [{ ...writer.bindings[0]!, target_field: "values/i" }] };
    const live = new Map([["t1", { version: 2, columns: [{ id: "c1", label: "ı" }] }]]);
    expect(orphanValueBindings(graph, live)).toEqual([{ nodeId: "w", field: "values/i" }]);
  });

  it("retains ambiguous live labels for server validation instead of erasing input", () => {
    const graph = {
      ...writer,
      bindings: [{ ...writer.bindings[0]!, target_field: "values/Score" }],
    };
    const live = new Map([
      [
        "t1",
        {
          version: 2,
          columns: [
            { id: "c1", label: "Score" },
            { id: "c2", label: "score" },
          ],
        },
      ],
    ]);
    expect(orphanValueBindings(graph, live)).toEqual([]);
  });

  it("leaves a writer whose table's columns are not known", () => {
    expect(orphanValueBindings(writer, new Map())).toEqual([]);
  });

  it("does not fetch tables or drop saved value bindings of switched-off writers", () => {
    const disabled = {
      ...writer,
      nodes: writer.nodes.map((node) => ({ ...node, disabled: true })),
    };
    const live = new Map([["t1", { version: 2, columns: [{ id: "c1", label: "Score" }] }]]);
    expect(recordWriterTables(disabled)).toEqual([]);
    expect(orphanValueBindings(disabled, live)).toEqual([]);
    expect(orphanValueBindings(writer, live)).toHaveLength(1);
  });

  it("lists only writers that bind per-column values", () => {
    expect(recordWriterTables(writer)).toEqual([{ tableId: "t1", version: 2 }]);
    expect(recordWriterTables(GRAPH)).toEqual([]);
  });
});

describe("isTableRefusalField", () => {
  it("names a step's own table, and a binding whose source is a table", () => {
    expect(isTableRefusalField("nodes.a.config.table", null)).toBe(true);
    expect(isTableRefusalField("bindings.0", GRAPH)).toBe(true);
  });

  it("leaves every other binding problem, and other fields, alone", () => {
    // `bindings.1` is a literal: a bad value there is not a table change.
    expect(isTableRefusalField("bindings.1", GRAPH)).toBe(false);
    expect(isTableRefusalField("bindings.0", null)).toBe(false);
    expect(isTableRefusalField("nodes.a.config.input_schema", GRAPH)).toBe(false);
  });
});

describe("node column dependencies", () => {
  it("checks filtered, sorted and written columns outside the output selection", () => {
    const graph = structuredClone(GRAPH);
    graph.nodes[0]!.definition_id = "table.record.update";
    graph.nodes[0]!.config = {
      table: ref(["c1"]),
      filters: [{ column_id: "filtered", op: "eq", value: "x" }],
      sort: { by: "sorted", direction: "asc" },
    };
    graph.bindings.push({
      target_node_id: "a",
      target_field: "values/written",
      source: { kind: "literal", value: "x" },
    });
    const used = nodeTableColumns(graph, { nodeId: "a", binding: null });
    expect(used).toEqual(["filtered", "sorted", "written"]);
    const bound = [column("c1"), column("filtered"), column("sorted"), column("written")];
    expect(safeToRebind(ref(["c1"]), table(bound), versions(bound), used)).toBe(true);
    expect(safeToRebind(ref(["c1"]), table([column("c1")]), versions(bound), used)).toBe(false);
    expect(nodeTableColumns(graph, { nodeId: "a", binding: 0 })).toEqual([]);
    expect(nodeTableColumns(graph, { nodeId: "absent", binding: null })).toEqual([]);
  });

  it("leaves whole-record inputs for explicit review instead of guessing their columns", () => {
    const graph = structuredClone(GRAPH);
    graph.nodes[0]!.definition_id = "table.record.create";
    graph.bindings.push({
      target_node_id: "a",
      target_field: "values",
      source: { kind: "literal", value: { c1: "x" } },
    });
    const used = nodeTableColumns(graph, { nodeId: "a", binding: null });
    expect(used).toBeNull();
    expect(safeToRebind(ref(["c1"]), table([column("c1")]), versions([column("c1")]), used)).toBe(
      false,
    );
  });

  it("refuses a selected column already missing from the bound schema", () => {
    expect(safeToRebind(ref(["missing"]), table([column("c1")]), versions([column("c1")]))).toBe(
      false,
    );
  });
});

describe("label-keyed writer dependencies", () => {
  function writer(field: string): WorkflowGraph {
    const graph = structuredClone(GRAPH);
    graph.nodes[0]!.definition_id = "table.record.create";
    graph.bindings = [
      {
        target_node_id: "a",
        target_field: `values/${field}`,
        source: { kind: "literal", value: 1 },
      },
    ];
    return graph;
  }

  it.each([
    ["sCoRe", "Score"],
    ["Score~1Delta", "Score/Delta"],
    ["Cost~0gross", "Cost~gross"],
    ["SS", "ẞ"],
  ])(
    "rebinds an unchanged labelled dependency %s after adding an unrelated column",
    (key, label) => {
      const before = [{ ...column("c1"), label }];
      const after = [...before, column("added")];
      const used = nodeTableColumns(writer(key), { nodeId: "a", binding: null }, { before, after });
      expect(used).toEqual(["c1"]);
      expect(safeToRebind(ref(["c1"]), table(after), versions(before), used)).toBe(true);
    },
  );

  it.each(["renamed", "reassigned", "ambiguous", "archived", "missing"])(
    "requires review when a label is %s",
    (change) => {
      const before = [{ ...column("c1"), label: "Score" }];
      const after =
        change === "renamed"
          ? [{ ...column("c1"), label: "New" }]
          : change === "reassigned"
            ? [
                { ...column("c1"), label: "New" },
                { ...column("c2"), label: "Score" },
              ]
            : change === "ambiguous"
              ? [...before, { ...column("c2"), label: "score" }]
              : change === "archived"
                ? [{ ...before[0]!, archived: true }]
                : [];
      expect(
        nodeTableColumns(writer("Score"), { nodeId: "a", binding: null }, { before, after }),
      ).toBeNull();
    },
  );

  it.each([
    { before: [] },
    {
      before: [
        { ...column("c1"), label: "Score" },
        { ...column("c2"), label: "score" },
      ],
    },
  ])("requires review if the historical label was missing or ambiguous", ({ before }) => {
    const after = [{ ...column("c1"), label: "Score" }];
    expect(
      nodeTableColumns(writer("Score"), { nodeId: "a", binding: null }, { before, after }),
    ).toBeNull();
  });

  it("keeps a type change blocked after resolving a label to its ID", () => {
    const before = [{ ...column("c1"), label: "Score" }];
    const after = [{ ...column("c1", "number"), label: "sCoRe" }];
    const used = nodeTableColumns(
      writer("Score"),
      { nodeId: "a", binding: null },
      { before, after },
    );
    expect(used).toEqual(["c1"]);
    expect(safeToRebind(ref(["c1"]), table(after), versions(before), used)).toBe(false);
  });

  it("gives an exact ID precedence over a conflicting label", () => {
    const columns = [
      { ...column("c1"), label: "Score" },
      { ...column("c2"), label: "c1" },
    ];
    expect(
      nodeTableColumns(
        writer("c1"),
        { nodeId: "a", binding: null },
        { before: columns, after: columns },
      ),
    ).toEqual(["c1"]);
  });
});
