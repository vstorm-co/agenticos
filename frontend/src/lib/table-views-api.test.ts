import { beforeEach, describe, expect, it, vi } from "vitest";

import { createView, deleteView, getView, listViews, updateView } from "./table-views-api";
import { apiClient } from "@/lib/api-client";

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
  it("lists every view when no kind is given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listViews("t1");
    expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/views", { params: undefined });
  });

  it("narrows to one kind when given", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    await listViews("t1", "kanban");
    expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/views", { params: { kind: "kanban" } });
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

it("getView reads one view", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ id: "v1" });
  await getView("t1", "v1");
  expect(apiClient.get).toHaveBeenCalledWith("/tables/t1/views/v1");
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
