import { beforeEach, describe, expect, it, vi } from "vitest";

import { createView, deleteView, listViews, updateView } from "./table-views-api";
import { apiClient } from "@/lib/api-client";
import type { TableViewUpdate } from "@/types/tables";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("listViews", () => {
  it("asks for the largest page the server answers", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listViews("t1");
    expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/views", { params: { limit: "100" } });
  });
});

it("createView posts to the views collection", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id: "v1" });
  await createView("t1", { name: "Board", kind: "kanban" });
  expect(apiClient.post).toHaveBeenCalledWith("/tables/t1/views", {
    name: "Board",
    kind: "kanban",
  });
});

it("updateView patches one view", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "v1" });
  await updateView("t1", "v1", { name: "Renamed" });
  expect(apiClient.patch).toHaveBeenCalledWith("/tables/t1/views/v1", { name: "Renamed" });
});

it("deleteView deletes one view", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  await deleteView("t1", "v1");
  expect(apiClient.delete).toHaveBeenCalledWith("/tables/t1/views/v1");
});

it("TableViewUpdate.config cannot be a partial config - the backend replaces the whole blob", () => {
  // A pinned type contract, not a runtime assertion: `config` used to type as
  // `Partial<TableViewConfig>`, which let a caller send `{ sort }` alone and
  // silently reset the view's filters, visible columns and grouping, because
  // the backend fills every field the request left out with its own default
  // rather than keeping the view's stored value. If the type below stops
  // erroring, the `@ts-expect-error` itself fails `tsc --noEmit`.
  function _typeOnly() {
    // @ts-expect-error - `config` must be a complete `TableViewConfig`.
    const partial: TableViewUpdate = { config: { sort: { by: "name", direction: "asc" } } };
    return partial;
  }
  expect(typeof _typeOnly).toBe("function");
});
