import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import { getNavPins, putNavPins } from "./nav-pins-api";

vi.mock("./api-client", async () => {
  const actual = await vi.importActual<typeof import("./api-client")>("./api-client");
  return { ...actual, apiClient: { get: vi.fn(), put: vi.fn() } };
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the nav pins client", () => {
  it("reads the caller's pins", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ item_ids: ["agents"] });
    await expect(getNavPins()).resolves.toEqual({ item_ids: ["agents"] });
    expect(apiClient.get).toHaveBeenCalledWith("/me/nav-pins");
  });

  it("replaces the pins under an item_ids envelope", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ item_ids: ["skills", "agents"] });
    await putNavPins(["skills", "agents"]);
    expect(apiClient.put).toHaveBeenCalledWith("/me/nav-pins", { item_ids: ["skills", "agents"] });
  });
});
