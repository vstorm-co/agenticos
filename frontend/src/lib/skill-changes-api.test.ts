import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./skill-changes-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "p-1" }], total: 1 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "p-1" });
});

describe("the skill changes client", () => {
  it("unwraps the list, because no caller wants the envelope", async () => {
    await expect(api.listSkillChanges()).resolves.toEqual([{ id: "p-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/skill-changes");
  });

  it("asks for one state when it is given one", async () => {
    // The reviewer's list is the pending ones; asking for everything and
    // filtering here would download every decision the deployment ever made.
    await api.listSkillChanges("pending");

    expect(apiClient.get).toHaveBeenCalledWith("/skill-changes?status=pending");
  });

  it("accepts and refuses through separate endpoints", async () => {
    // Two verbs rather than a PATCH of `status`: a decision is terminal and the
    // server refuses a second one, which reads better as an action than a field.
    await api.applySkillChange("p-1");
    expect(apiClient.post).toHaveBeenCalledWith("/skill-changes/p-1/apply");

    await api.discardSkillChange("p-1");
    expect(apiClient.post).toHaveBeenCalledWith("/skill-changes/p-1/discard");
  });
});
