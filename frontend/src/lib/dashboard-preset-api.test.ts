import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { createPreset, deletePreset, listPresets } from "./dashboard-preset-api";

vi.mock("./api-client", async () => {
  const actual = await vi.importActual<typeof import("./api-client")>("./api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the dashboard preset client", () => {
  it("returns the list's items, dropping the envelope", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "p1", name: "Monday review", entries: [] }],
      total: 1,
    });
    await expect(listPresets()).resolves.toEqual([
      { id: "p1", name: "Monday review", entries: [] },
    ]);
    expect(apiClient.get).toHaveBeenCalledWith("/me/dashboard-layout/presets");
  });

  it("creates a preset under a name-and-entries body", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "p1", name: "Monday review", entries: [] });
    await createPreset("Monday review", [{ widget: "runs", span: "s8", rows: "r3" }]);
    expect(apiClient.post).toHaveBeenCalledWith("/me/dashboard-layout/presets", {
      name: "Monday review",
      entries: [{ widget: "runs", span: "s8", rows: "r3" }],
    });
  });

  it("deletes a preset by id", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await deletePreset("p1");
    expect(apiClient.delete).toHaveBeenCalledWith("/me/dashboard-layout/presets/p1");
  });
});
