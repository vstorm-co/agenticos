import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { getTable, listTables } from "./tables-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn() },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("tables-api", () => {
  it("lists tables with no pagination params", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await expect(listTables()).resolves.toEqual({ items: [], total: 0 });
    expect(apiClient.get).toHaveBeenCalledWith("/tables", undefined);
  });

  it("lists tables with only a skip, defaulting the limit", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listTables({ skip: 5 });
    expect(apiClient.get).toHaveBeenCalledWith("/tables", { params: { skip: "5", limit: "50" } });
  });

  it("lists tables with only a limit, defaulting the skip", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listTables({ limit: 100 });
    expect(apiClient.get).toHaveBeenCalledWith("/tables", { params: { skip: "0", limit: "100" } });
  });

  it("fetches one table by id, columns and all", async () => {
    const table = { id: "t1", name: "Leads", columns: [], schema_version: 3 };
    vi.mocked(apiClient.get).mockResolvedValue(table);
    await expect(getTable("t1")).resolves.toBe(table);
    expect(apiClient.get).toHaveBeenCalledWith("/tables/t1");
  });
});
