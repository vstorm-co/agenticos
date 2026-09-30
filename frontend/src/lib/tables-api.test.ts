import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  archiveTable,
  batchRefusal,
  createRecord,
  createRecords,
  createTable,
  deleteRecord,
  exportRecords,
  getRecord,
  getTable,
  listTables,
  queryRecords,
  updateRecord,
  updateSchema,
  updateTable,
} from "./tables-api";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "./file-access";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    raw: vi.fn(),
  },
}));
vi.mock("./file-access", () => ({ saveBlob: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("listTables", () => {
  it("builds no filter params for an empty query", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listTables();
    expect(apiClient.get).toHaveBeenCalledWith("/tables", { params: { skip: "0", limit: "50" } });
  });

  it("passes search and includeArchived through to the wire params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listTables({ search: "ord", includeArchived: true, skip: 10, limit: 25 });
    expect(apiClient.get).toHaveBeenCalledWith("/tables", {
      params: { q: "ord", include_archived: "true", skip: "10", limit: "25" },
    });
  });

  it("passes sort through to the wire params when given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listTables({ sort: "updated_at" });
    expect(apiClient.get).toHaveBeenCalledWith("/tables", {
      params: { sort: "updated_at", skip: "0", limit: "50" },
    });
  });
});

it("createTable posts to the collection route", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "t1" });
  await createTable({ name: "Orders" });
  expect(apiClient.post).toHaveBeenCalledWith("/tables", { name: "Orders" });
});

it("getTable reads one table", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "t1" });
  await getTable("t1");
  expect(apiClient.get).toHaveBeenCalledWith("/tables/t1");
});

it("updateTable patches one table", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "t1" });
  await updateTable("t1", { name: "Renamed" });
  expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1", { name: "Renamed" });
});

it("archiveTable posts to the archive action", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "t1" });
  await archiveTable("t1");
  expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/archive");
});

it("updateSchema puts the full column list", async () => {
  vi.mocked(apiClient.put).mockResolvedValue({ id: "t1" });
  await updateSchema("t1", { expected_version: 1, columns: [] });
  expect(apiClient.put).toHaveBeenCalledWith("/tables/t1/schema", {
    expected_version: 1,
    columns: [],
  });
});

it("queryRecords posts the typed query", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ items: [], skip: 0, limit: 50, has_more: false });
  await queryRecords("t1", { filters: [], skip: 0, limit: 50 });
  expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records/query", {
    filters: [],
    skip: 0,
    limit: 50,
  });
});

it("createRecord posts to the records collection", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "r1" });
  await createRecord("t1", { values: {} });
  expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records", { values: {} });
});

it("getRecord reads one record", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "r1" });
  await getRecord("t1", "r1");
  expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/records/r1");
});

it("updateRecord patches named cells with the expected revision", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1" });
  await updateRecord("t1", "r1", { expected_revision: 2, values: { c1: "x" } });
  expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/records/r1", {
    expected_revision: 2,
    values: { c1: "x" },
  });
});

it("deleteRecord sends the expected revision as a query param", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  await deleteRecord("t1", "r1", 3);
  expect(apiClient.delete).toHaveBeenCalledWith("/tables/t1/records/r1?expected_revision=3");
});

describe("bulk records", () => {
  it("creates a batch in one call", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ created: 1, failed: [] });

    await createRecords("t1", [{ values: {} }]);

    expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/records/batch", {
      records: [{ values: {} }],
    });
  });

  it("saves an export under the name the server gives, or a plain one", async () => {
    const blob = new Blob(["a"]);
    const answer = (disposition: string | null) =>
      ({
        headers: new Headers(disposition ? { "content-disposition": disposition } : {}),
        blob: async () => blob,
      }) as unknown as Response;
    vi.mocked(apiClient.raw)
      .mockResolvedValueOnce(answer('attachment; filename="Orders.csv"'))
      .mockResolvedValueOnce(answer(null));

    await exportRecords("t1", { search: "ada" });
    await exportRecords("t1", {});

    expect(apiClient.raw).toHaveBeenCalledWith("/tables/t1/records/export", {
      method: "POST",
      body: { search: "ada" },
    });
    expect(vi.mocked(saveBlob).mock.calls).toEqual([
      [blob, "Orders.csv"],
      [blob, "table.csv"],
    ]);
  });
});

describe("batchRefusal", () => {
  it("is the error a single create would have thrown", () => {
    const error = batchRefusal({
      index: 0,
      code: "ALREADY_EXISTS",
      message: "Taken",
      details: null,
    });

    expect([error.status, error.code, error.message]).toEqual([422, "ALREADY_EXISTS", "Taken"]);
  });
});
