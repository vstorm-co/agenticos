import { beforeEach, expect, it, vi } from "vitest";

import { listDecidableWorkflowApprovals } from "./approvals-api";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", () => ({ apiClient: { get } }));

beforeEach(() => {
  get.mockReset().mockResolvedValue({ items: [], total: 0 });
});

it("asks for the requests the caller may decide, as many rows as the reader shows", async () => {
  await listDecidableWorkflowApprovals(5);
  expect(get).toHaveBeenCalledWith("/workflow-approvals", {
    params: { decidable: "true", limit: "5" },
  });
});
