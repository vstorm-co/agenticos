import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "./api-client";
import { deleteLayout, getLayout, putLayout } from "./dashboard-layout-api";

vi.mock("./api-client", async () => {
  const actual = await vi.importActual<typeof import("./api-client")>("./api-client");
  return { ...actual, apiClient: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the dashboard layout client", () => {
  it("returns the saved arrangement when there is one", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ entries: [{ widget: "runs", span: "s8" }] });
    await expect(getLayout()).resolves.toEqual({ entries: [{ widget: "runs", span: "s8" }] });
    expect(apiClient.get).toHaveBeenCalledWith("/me/dashboard-layout");
  });

  it("reads a 404 as no saved layout, not as an error", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "No saved dashboard layout"));
    await expect(getLayout()).resolves.toBeNull();
  });

  it("rethrows any other failure", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(500, "boom"));
    await expect(getLayout()).rejects.toBeInstanceOf(ApiError);
  });

  it("saves the arrangement under an entries envelope", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ entries: [] });
    await putLayout([{ widget: "spend", span: "s6" }]);
    expect(apiClient.put).toHaveBeenCalledWith("/me/dashboard-layout", {
      entries: [{ widget: "spend", span: "s6" }],
    });
  });

  it("resets by deleting", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await deleteLayout();
    expect(apiClient.delete).toHaveBeenCalledWith("/me/dashboard-layout");
  });
});
