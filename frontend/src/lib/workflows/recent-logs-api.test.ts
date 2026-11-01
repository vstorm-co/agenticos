import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { getRecentWorkflowLogs } from "./recent-logs-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn() } };
});

beforeEach(() => vi.clearAllMocks());

describe("recent-logs-api", () => {
  it("reads the first page of the newest lines, as many as asked for", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], counts: {} });
    await getRecentWorkflowLogs(8);
    expect(apiClient.get).toHaveBeenCalledWith("/workflow-logs", {
      params: { skip: "0", limit: "8" },
    });
  });
});
