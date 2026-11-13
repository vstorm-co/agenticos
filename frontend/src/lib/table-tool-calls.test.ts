import { describe, expect, it } from "vitest";

import type { ColumnDef } from "@/types/tables";

import {
  isTableTool,
  parseTableCall,
  readTableAnswer,
  sortTarget,
  titleColumn,
} from "./table-tool-calls";

const TABLE = "ed7b79b6-02bf-4303-a08c-9b95e37af56f";
const STATUS = "e30bcc3d-2c44-4aae-86ff-cb149b75f8a1";
const QUEUED = "8c6bb5b9-bbda-42b3-a4cd-4e120f1f2d4f";

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

const record = { id: "r1", table_id: TABLE, values: { [STATUS]: QUEUED }, revision: 2 };

describe("parseTableCall", () => {
  it("reads a query's filters, order, search and page size", () => {
    const call = parseTableCall("agenticos_query_virtual_table", {
      table_id: TABLE,
      query: {
        sort: { by: "created_at", direction: "asc" },
        limit: 20,
        search: "agents",
        filters: [{ op: "eq", value: QUEUED, column_id: STATUS }, { op: "eq" }, "junk"],
      },
    });
    expect(call).toEqual({
      tool: "query",
      tableId: TABLE,
      recordId: null,
      externalId: null,
      values: null,
      query: {
        filters: [{ op: "eq", value: QUEUED, column_id: STATUS }],
        sort: { by: "created_at", direction: "asc" },
        search: "agents",
        limit: 20,
      },
    });
  });

  it("reads arguments that arrived as a JSON string, and a query left out", () => {
    const call = parseTableCall(
      "agenticos_query_virtual_table",
      JSON.stringify({ table_id: TABLE, query: { sort: { by: STATUS, direction: "desc" } } }),
    );
    expect(call?.query).toEqual({
      filters: [],
      sort: { by: STATUS, direction: "desc" },
      search: null,
      limit: null,
    });
    expect(parseTableCall("agenticos_query_virtual_table", { table_id: TABLE })?.query).toEqual({
      filters: [],
      sort: null,
      search: null,
      limit: null,
    });
  });

  it("reads the cells each write sends, wherever its tool nests them", () => {
    const values = { [STATUS]: QUEUED };
    expect(
      parseTableCall("agenticos_add_virtual_table_record", {
        table_id: TABLE,
        values,
        external_id: "hn-1",
      }),
    ).toMatchObject({ tool: "add", values, externalId: "hn-1" });
    expect(
      parseTableCall("agenticos_update_virtual_table_record", {
        table_id: TABLE,
        record_id: "r1",
        update: { expected_revision: 2, values },
      }),
    ).toMatchObject({ tool: "update", values, recordId: "r1" });
    expect(
      parseTableCall("agenticos_upsert_virtual_table_record", {
        table_id: TABLE,
        external_id: "hn-1",
        record: { values },
      }),
    ).toMatchObject({ tool: "upsert", values });
    expect(
      parseTableCall("agenticos_delete_virtual_table_record", {
        table_id: TABLE,
        record_id: "r1",
        expected_revision: 2,
      }),
    ).toMatchObject({ tool: "delete", values: null, query: null });
    expect(
      parseTableCall("agenticos_update_virtual_table_record", { table_id: TABLE, update: "x" })
        ?.values,
    ).toBeNull();
  });

  it("refuses another tool, a call without its table, and unreadable arguments", () => {
    expect(parseTableCall("agenticos_get_virtual_table", { table_id: TABLE })).toBeNull();
    expect(parseTableCall("agenticos_query_virtual_table", { table_id: "" })).toBeNull();
    expect(parseTableCall("agenticos_query_virtual_table", "{not json")).toBeNull();
    expect(parseTableCall("agenticos_query_virtual_table", [TABLE])).toBeNull();
    expect(parseTableCall("agenticos_query_virtual_table", null)).toBeNull();
  });
});

describe("isTableTool", () => {
  it("names the platform's record tools only", () => {
    expect(isTableTool("agenticos_virtual_table_record_exists")).toBe(true);
    expect(isTableTool("agenticos_get_virtual_table_record")).toBe(true);
    expect(isTableTool("agenticos_create_virtual_table")).toBe(false);
    expect(isTableTool("query_records")).toBe(false);
  });
});

describe("readTableAnswer", () => {
  it("reads a page of records, dropping items that are not records", () => {
    expect(
      readTableAnswer("query", JSON.stringify({ items: [record, { id: 3 }], has_more: true })),
    ).toEqual({ kind: "records", records: [record], hasMore: true });
    expect(readTableAnswer("query", { items: [] })).toEqual({
      kind: "records",
      records: [],
      hasMore: false,
    });
    expect(readTableAnswer("query", { items: "none" })).toBeNull();
  });

  it("reads one record, an existence check and a deletion", () => {
    expect(readTableAnswer("update", record)).toEqual({ kind: "record", record });
    expect(readTableAnswer("get", { id: "r1" })).toBeNull();
    expect(readTableAnswer("exists", { exists: false })).toEqual({ kind: "exists", exists: false });
    expect(readTableAnswer("exists", {})).toBeNull();
    expect(readTableAnswer("delete", { deleted: true })).toEqual({ kind: "deleted" });
    expect(readTableAnswer("delete", {})).toBeNull();
  });

  it("refuses an error envelope and a sentence", () => {
    expect(readTableAnswer("query", { error: { message: "Refused" } })).toBeNull();
    expect(readTableAnswer("query", "Tool failed")).toBeNull();
  });
});

describe("titleColumn and sortTarget", () => {
  const title = column({ id: "t", label: "Title" });
  const columns = [
    column({ id: "s", type: "single_select" }),
    column({ id: "old", archived: true }),
    column({ id: "sys", system: "created_by" }),
    title,
  ];

  it("reads a record by its first live text column", () => {
    expect(titleColumn(columns)).toBe(title);
    expect(titleColumn([columns[0]!])).toBeNull();
  });

  it("names a sort by its column or by the record's own dates", () => {
    expect(sortTarget("created_at", columns)).toEqual({ field: "createdAt" });
    expect(sortTarget("updated_at", columns)).toEqual({ field: "updatedAt" });
    expect(sortTarget("t", columns)).toEqual({ column: title });
    expect(sortTarget("gone", columns)).toBeNull();
  });
});
