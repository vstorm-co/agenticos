import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { MediaSurfaceContext } from "@/lib/generated-media";
import type { ToolCall } from "@/types";
import type { ColumnDef, TableRead } from "@/types/tables";

import { TableApprovalSummary, TableToolResult } from "./table-call";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const TABLE = "ed7b79b6-02bf-4303-a08c-9b95e37af56f";
const TITLE = "cd256dc5-db77-493b-9368-c42d53c58805";
const CONTENT = "4505056e-daa1-403d-87a3-b21a2ed7c3dd";
const STATUS = "e30bcc3d-2c44-4aae-86ff-cb149b75f8a1";
const PUBLISHED = "5a0e8b52-6c4f-4d55-9a3e-1b2c3d4e5f60";
const QUEUED = "8c6bb5b9-bbda-42b3-a4cd-4e120f1f2d4f";
const WORTH = "299ff8f2-b293-4198-be6c-e1ece853cc4a";

function column(overrides: Partial<ColumnDef>): ColumnDef {
  return {
    id: "c",
    label: "Column",
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
    ...overrides,
  };
}

const table: TableRead = {
  id: TABLE,
  name: "hacker_news_table",
  description: null,
  visibility: "private",
  owner_user_id: null,
  schema_version: 3,
  archived_at: null,
  created_at: "2026-11-01T10:00:00Z",
  updated_at: null,
  can_edit: true,
  can_restore: false,
  can_manage: true,
  columns: [
    column({ id: TITLE, label: "Title" }),
    column({ id: CONTENT, label: "Content", type: "long_text" }),
    column({ id: PUBLISHED, label: "Published", type: "date" }),
    column({
      id: STATUS,
      label: "status",
      type: "single_select",
      options: [
        { id: QUEUED, label: "To be analyzed", archived: false },
        { id: WORTH, label: "Worth sharing", archived: false },
      ],
    }),
  ],
};

function row(id: string, title: string) {
  return {
    id,
    table_id: TABLE,
    values: { [TITLE]: title, [CONTENT]: "<html>…</html>", [STATUS]: QUEUED },
    revision: 1,
  };
}

function call(name: string, args: Record<string, unknown>, result?: unknown): ToolCall {
  return {
    id: "call",
    name,
    tool_id: name,
    args: { table_id: TABLE, ...args },
    result: result === undefined ? undefined : JSON.stringify(result),
    status: result === undefined ? "running" : "completed",
  } as ToolCall;
}

function show(node: ReactNode, surface: "session" | "hosted" = "session") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaSurfaceContext.Provider
        value={surface === "session" ? { kind: "session" } : { kind: "hosted", publicKey: "k" }}
      >
        {node}
      </MediaSurfaceContext.Provider>
    </QueryClientProvider>,
  );
}

function shown(toolCall: ToolCall, surface: "session" | "hosted" = "session") {
  return show(
    <TableToolResult toolCall={toolCall} toolName={toolCall.name} resultText="" />,
    surface,
  );
}

const queued = {
  query: {
    sort: { by: "created_at", direction: "asc" },
    limit: 20,
    filters: [{ op: "eq", value: QUEUED, column_id: STATUS }],
  },
};

describe("table tool results", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(table);
  });

  it("reads a query's conditions and its page in the table's own labels", async () => {
    const records = Array.from({ length: 12 }, (_, index) => row(`r${index}`, `Story ${index}`));
    shown(
      call("agenticos_query_virtual_table", queued, {
        items: records,
        has_more: true,
      }),
    );

    expect(await screen.findByRole("link", { name: "hacker_news_table" })).toHaveAttribute(
      "href",
      `/tables/${TABLE}`,
    );
    expect(apiClient.get).toHaveBeenCalledWith(`/tables/${TABLE}`);
    expect(screen.getByText("To be analyzed", { selector: "li span" })).toBeInTheDocument();
    expect(screen.getByText("is")).toBeInTheDocument();
    expect(screen.getByText("Sorted by Created, ascending · At most 20 records")).toBeVisible();
    expect(screen.getByText("12 records found · more on the next page")).toBeVisible();
    // The title and the column it filtered on - never the article body.
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Title",
      "status",
    ]);
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.getByText("and 2 more records")).toBeVisible();
    expect(screen.queryByText(STATUS)).not.toBeInTheDocument();
  });

  it("names each kind of condition and a sort on a column", async () => {
    shown(
      call(
        "agenticos_query_virtual_table",
        {
          query: {
            sort: { by: TITLE, direction: "desc" },
            search: "agents",
            filters: [
              { op: "in", value: [QUEUED, WORTH], column_id: STATUS },
              { op: "is_null", value: false, column_id: TITLE },
              { op: "lt", value: "2026-11-01", column_id: PUBLISHED },
              { op: "eq", value: "x", column_id: "gone" },
            ],
          },
        },
        { items: [], has_more: false },
      ),
    );

    expect(await screen.findByText("To be analyzed, Worth sharing")).toBeVisible();
    expect(screen.getByText("is any of")).toBeVisible();
    expect(screen.getByText("is not empty")).toBeVisible();
    expect(screen.getByText("before")).toBeVisible();
    expect(screen.getByText("gone")).toHaveClass("font-mono");
    expect(screen.getByText("Matching “agents”")).toBeVisible();
    expect(screen.getByText("Sorted by Title, descending")).toBeVisible();
    expect(screen.getByText("No records found")).toBeVisible();
  });

  it("reads a page of a table with no text column, and cells a record left empty", async () => {
    const flag = column({ id: "flag", label: "Shared", type: "boolean" });
    vi.mocked(apiClient.get).mockResolvedValue({
      ...table,
      columns: [table.columns[2]!, table.columns[3]!, flag],
    });
    shown(
      call(
        "agenticos_query_virtual_table",
        {
          query: {
            limit: 1,
            filters: [
              { op: "eq", value: "2026-11-01", column_id: PUBLISHED },
              { op: "eq", value: true, column_id: "flag" },
              { op: "in", value: ["a", "b"], column_id: "gone" },
            ],
          },
        },
        { items: [{ id: "r1", table_id: TABLE, values: { flag: true }, revision: 1 }] },
      ),
    );

    expect(await screen.findByText("At most 1 record")).toBeVisible();
    expect(screen.getAllByText("is")).toHaveLength(2);
    expect(screen.getByText("a, b")).toBeVisible();
    expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Published",
      "Shared",
    ]);
    expect(screen.getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["", "True"]);
  });

  it("says a query with no conditions reads every record, and a sort it cannot name", async () => {
    shown(call("agenticos_query_virtual_table", { query: { sort: { by: "gone" } } }));
    expect(await screen.findByText("All records")).toBeVisible();
    expect(screen.getByText("Sorted by gone, ascending")).toBeVisible();
  });

  it("reads the cells a write sends, and the record it answered with", async () => {
    shown(
      call(
        "agenticos_update_virtual_table_record",
        { record_id: "r1", update: { expected_revision: 1, values: { [STATUS]: WORTH } } },
        { ...row("r1", "Agents in prod"), revision: 2 },
      ),
    );
    expect(await screen.findByText("Worth sharing")).toBeVisible();
    expect(screen.getByText("status")).toBeVisible();
    expect(screen.getByText("Record “Agents in prod” · revision 2")).toBeVisible();
  });

  it("answers an upsert, an existence check and a deletion in words", async () => {
    const untitled = { id: "r2", table_id: TABLE, values: { [STATUS]: QUEUED }, revision: 1 };
    const { unmount } = shown(
      call(
        "agenticos_upsert_virtual_table_record",
        { external_id: "hn-1", record: { values: { [STATUS]: QUEUED, unknown: 3 } } },
        untitled,
      ),
    );
    expect(await screen.findByText("External ID: hn-1")).toBeVisible();
    expect(screen.getByText("Record · revision 1")).toBeVisible();
    expect(screen.getByText("unknown")).toHaveClass("font-mono");
    unmount();

    const exists = shown(
      call("agenticos_virtual_table_record_exists", { external_id: "hn-1" }, { exists: true }),
    );
    expect(await screen.findByText("A record with this external ID exists")).toBeVisible();
    exists.unmount();

    const missing = shown(
      call("agenticos_virtual_table_record_exists", { external_id: "hn-2" }, { exists: false }),
    );
    expect(await screen.findByText("No record has this external ID")).toBeVisible();
    missing.unmount();

    shown(
      call(
        "agenticos_delete_virtual_table_record",
        { record_id: "r1", expected_revision: 2 },
        { deleted: true },
      ),
    );
    expect(await screen.findByText("Record deleted")).toBeVisible();
  });

  it("titles a record only from a text column the table has", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ ...table, columns: [table.columns[3]!] });
    shown(call("agenticos_get_virtual_table_record", { record_id: "r1" }, row("r1", "x")));
    expect(await screen.findByText("Record · revision 1")).toBeVisible();
  });

  it("shows the call as sent when the table cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Forbidden"));
    shown(call("agenticos_query_virtual_table", queued, { items: [], has_more: false }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.getByText("Arguments")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("reads no table on a hosted page, whose visitor has no session", () => {
    shown(call("agenticos_query_virtual_table", queued, { items: [] }), "hosted");
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(screen.getByText("Arguments")).toBeVisible();
  });

  it("keeps a refusal in the generic view, which shows it whole", async () => {
    shown(call("agenticos_query_virtual_table", queued, { error: { message: "No access" } }));
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});

describe("table approval summary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(table);
  });

  it("names a parked write's table and cells", async () => {
    show(
      <TableApprovalSummary
        toolName="agenticos_add_virtual_table_record"
        args={{ table_id: TABLE, values: { [TITLE]: "New story", [STATUS]: QUEUED } }}
      />,
    );
    expect(await screen.findByRole("link", { name: "hacker_news_table" })).toBeVisible();
    expect(screen.getByText("New story")).toBeVisible();
    expect(screen.getByText("To be analyzed")).toBeVisible();
  });

  it("reads nothing for any other tool", () => {
    const { container } = show(
      <TableApprovalSummary toolName="agenticos_create_routine" args={{ table_id: TABLE }} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("stays empty until the table is read", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { container } = show(
      <TableApprovalSummary
        toolName="agenticos_delete_virtual_table_record"
        args={{ table_id: TABLE, record_id: "r1" }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
