import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkflowTableDrift } from "./use-workflow-table-drift";
import * as api from "@/lib/tables-api";
import { qk } from "@/lib/query-keys";
import type { TableIORef, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import type { ColumnDef } from "@/types/tables";

vi.mock("@/lib/tables-api", () => ({
  listTables: vi.fn(),
  getTable: vi.fn(),
  listSchemaVersions: vi.fn(),
}));

const store = useWorkflowEditorStore;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const column = (id: string, type = "text") =>
  ({ id, label: id, type, archived: false }) as ColumnDef;
const ref = (column_ids: string[] | null, schema_version = 1): TableIORef => ({
  kind: "table",
  table_id: "t1",
  column_ids,
  schema_version,
});

function seed(table: TableIORef, bound: TableIORef | null = null) {
  store.getState().seedGraph({
    entry_node_id: "a",
    nodes: [
      {
        id: "a",
        definition_id: "table.read",
        definition_version: 1,
        config: { table },
        layout: { x: 0, y: 0 },
      },
      {
        id: "b",
        definition_id: "agent",
        definition_version: 1,
        config: {},
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: bound ? [{ target_node_id: "b", target_field: "rows", source: bound }] : [],
    scopes: [],
  } as unknown as WorkflowGraph);
}

/** The table now at version 2 with `now`, having had `before` at version 1. */
function serve(before: ColumnDef[], now: ColumnDef[]) {
  vi.mocked(api.listTables).mockResolvedValue({
    items: [{ id: "t1", schema_version: 2 }] as never,
    total: 1,
  });
  vi.mocked(api.getTable).mockResolvedValue({ id: "t1", schema_version: 2, columns: now } as never);
  vi.mocked(api.listSchemaVersions).mockResolvedValue({
    items: [
      { version: 1, columns: before, created_by: null, created_at: "" },
      { version: 2, columns: now, created_by: null, created_at: "" },
    ],
  });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => store.getState().teardown());

describe("useWorkflowTableDrift", () => {
  it("moves a reference onto the current schema when only other columns changed", async () => {
    serve([column("c1")], [column("c1"), column("c2")]);
    seed(ref(["c1"]));

    renderHook(() => useWorkflowTableDrift(true), { wrapper });

    await waitFor(() =>
      expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"], 2)),
    );
    expect(store.getState().isDirty).toBe(true);
    expect(store.getState().tableDrift).toEqual([]);
  });

  it("reads a table cached from before the change again, rather than rebinding to it", async () => {
    // The step's settings read the table before a column was added: that copy
    // still names version 1, while the list already says 2.
    serve([column("c1")], [column("c1"), column("c2")]);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 300_000 } },
    });
    client.setQueryData(qk.workflows.table("t1"), {
      id: "t1",
      schema_version: 1,
      columns: [column("c1")],
    });
    seed(ref(["c1"]));

    renderHook(() => useWorkflowTableDrift(true), {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    await waitFor(() =>
      expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"], 2)),
    );
    expect(api.getTable).toHaveBeenCalled();
  });

  it("leaves a reference whose column was retyped for the author, as drift on its step", async () => {
    serve([column("c1")], [column("c1", "number")]);
    seed(ref(["c1"]), ref(["c1"]));

    renderHook(() => useWorkflowTableDrift(true), { wrapper });

    await waitFor(() => expect(store.getState().tableDrift).toHaveLength(2));
    expect(store.getState().tableDrift).toEqual([
      { nodeId: "a", field: null, site: { nodeId: "a", binding: null }, rebound: ref(["c1"], 2) },
      { nodeId: "b", field: "rows", site: { nodeId: "b", binding: 0 }, rebound: ref(["c1"], 2) },
    ]);
    expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"]));
    expect(store.getState().isDirty).toBe(false);
    expect(api.listSchemaVersions).toHaveBeenCalledWith("t1", 1);
    expect(api.listSchemaVersions).toHaveBeenCalledWith("t1", 2);
    expect(vi.mocked(api.listSchemaVersions).mock.calls.every((args) => args.length === 2)).toBe(
      true,
    );

    // Accepting it - the toolbar's one click - clears the drift.
    store
      .getState()
      .rebindTables(
        store.getState().tableDrift.map((entry) => ({ site: entry.site, ref: entry.rebound })),
      );
    await waitFor(() => expect(store.getState().tableDrift).toEqual([]));
  });

  it.each(["filter", "sort", "retyped"])(
    "keeps drift until the changed %s dependency is edited",
    async (kind) => {
      serve(
        [column("c1"), column("changed")],
        kind === "retyped" ? [column("c1"), column("changed", "number")] : [column("c1")],
      );
      seed(ref(["c1"]));
      store.getState().updateNodeConfig("a", {
        table: ref(["c1"]),
        ...(kind === "sort"
          ? { sort: { by: "changed", direction: "asc" } }
          : { filters: [{ column_id: "changed", op: "eq", value: "x" }] }),
      });
      renderHook(() => useWorkflowTableDrift(true), { wrapper });
      await waitFor(() => expect(store.getState().tableDrift[0]?.requiresReview).toBe(true));
      act(() =>
        store
          .getState()
          .rebindTables(
            store.getState().tableDrift.map((entry) => ({ site: entry.site, ref: entry.rebound })),
          ),
      );
      expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"]));
      expect(store.getState().tableDrift[0]?.requiresReview).toBe(true);
      act(() => store.getState().updateNodeConfig("a", { table: ref(["c1"]) }));
      await waitFor(() =>
        expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"], 2)),
      );
      expect(store.getState().tableDrift).toEqual([]);
    },
  );

  it("reads the tables again when a refusal asks, and when the tab comes back", async () => {
    serve([column("c1")], [column("c1"), column("c2")]);
    seed(ref(["c1"], 2));
    renderHook(() => useWorkflowTableDrift(true), { wrapper });
    await waitFor(() => expect(api.listTables).toHaveBeenCalledTimes(1));

    act(() => store.getState().refreshTables());
    await waitFor(() => expect(api.listTables).toHaveBeenCalledTimes(2));

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(api.listTables).toHaveBeenCalledTimes(3));
  });

  it("drops a record value bound to a column the table has since archived", async () => {
    // Already on the current schema; the form no longer shows the archived
    // column, so its binding could not be removed by hand and failed every run.
    vi.mocked(api.listTables).mockResolvedValue({
      items: [{ id: "t1", schema_version: 2 }] as never,
      total: 1,
    });
    vi.mocked(api.getTable).mockResolvedValue({
      id: "t1",
      schema_version: 2,
      columns: [column("c1"), { ...column("old"), archived: true }],
    } as never);
    const literal = { kind: "literal", value: "x" };
    store.getState().seedGraph({
      entry_node_id: "w",
      nodes: [
        {
          id: "w",
          definition_id: "table.record.create",
          definition_version: 1,
          config: { table: ref(null, 2) },
          layout: { x: 0, y: 0 },
        },
      ],
      edges: [],
      bindings: [
        { target_node_id: "w", target_field: "values/c1", source: literal },
        { target_node_id: "w", target_field: "values/old", source: literal },
        { target_node_id: "w", target_field: "external_id", source: literal },
      ],
      scopes: [],
    } as unknown as WorkflowGraph);

    renderHook(() => useWorkflowTableDrift(true), { wrapper });

    await waitFor(() =>
      expect(store.getState().graph!.bindings.map((binding) => binding.target_field)).toEqual([
        "values/c1",
        "external_id",
      ]),
    );
    expect(api.listSchemaVersions).not.toHaveBeenCalled();
  });

  it("fetches nothing and changes nothing for a reader", async () => {
    serve([column("c1")], [column("c1"), column("c2")]);
    seed(ref(["c1"]));

    renderHook(() => useWorkflowTableDrift(false), { wrapper });

    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(api.listTables).not.toHaveBeenCalled();
    expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"]));
  });
});

it.each([
  ["trigger.table_record", { filters: [{ column_id: "c2", op: "eq", value: "x" }] }],
  ["table.record.query", { sort: { by: "c2", direction: "asc" } }],
] as const)(
  "keeps %s drift when an unselected dependent column changes",
  async (definition, extra) => {
    serve([column("c1"), column("c2")], [column("c1"), column("c2", "number")]);
    seed(ref(["c1"]));
    const graph = store.getState().graph!;
    graph.nodes[0]!.definition_id = definition;
    graph.nodes[0]!.config = { table: ref(["c1"]), ...extra };
    renderHook(() => useWorkflowTableDrift(true), { wrapper });
    await waitFor(() => expect(store.getState().tableDrift).toHaveLength(1));
    expect(store.getState().graph!.nodes[0]!.config.table).toEqual(ref(["c1"]));
    expect(store.getState().isDirty).toBe(false);
  },
);
