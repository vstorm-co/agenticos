import { beforeEach, describe, expect, it, vi } from "vitest";

import { listSystemAgents, updateSystemAgent } from "./system-agents-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe("the system agents API", () => {
  it("lists the roles", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ role: "memory_maintenance" }] });

    await expect(listSystemAgents()).resolves.toEqual([{ role: "memory_maintenance" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/system-agents");
  });

  it("replaces a role's switch, model and budget", async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ role: "memory_maintenance" });

    await updateSystemAgent("memory_maintenance", {
      enabled: true,
      model_profile_id: "m",
      monthly_budget_usd: null,
    });

    expect(apiClient.put).toHaveBeenCalledWith("/system-agents/memory_maintenance", {
      enabled: true,
      model_profile_id: "m",
      monthly_budget_usd: null,
    });
  });
});
