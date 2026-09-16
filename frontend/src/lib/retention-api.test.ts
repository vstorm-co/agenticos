import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRetention, putRetention, RETENTION_CLASSES } from "./retention-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));

const POLICY = {
  requested: { conversations: 30 },
  effective: { conversations: 30, audit: 2190 },
  ceilings: {},
  audit_floor_days: 2190,
  conflicts: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue(POLICY);
  vi.mocked(apiClient.put).mockResolvedValue(POLICY);
});

describe("the retention API", () => {
  it("reads one organization's policy by its id, not the active one", async () => {
    // The page names an organization in its path and *is* that organization,
    // which is the distinction #1032 was about.
    await expect(getRetention("o-1")).resolves.toEqual(POLICY);
    expect(apiClient.get).toHaveBeenCalledWith("/orgs/o-1/retention");
  });

  it("sends the periods under the key the API reads", async () => {
    await putRetention("o-1", { runs: 90, conversations: null });

    expect(apiClient.put).toHaveBeenCalledWith("/orgs/o-1/retention", {
      retention_days: { runs: 90, conversations: null },
    });
  });

  it("lists the classes in the order the page shows them", () => {
    // The order is the settings page's, so it is here rather than derived from
    // whatever order the server happened to serialize.
    expect(RETENTION_CLASSES).toEqual([
      "conversations",
      "runs",
      "workspaces",
      "memory",
      "knowledge_documents",
      "audit",
    ]);
  });
});
