import { expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { listDurableTasks } from "./tasks-api";
vi.mock("./api-client", () => ({ apiClient: { get: vi.fn() } }));
it("reads the selected task table's next page and forwards cancellation", async () => {
  const controller = new AbortController();
  const page = { items: [], has_more: false };
  vi.mocked(apiClient.get).mockResolvedValue(page);
  expect(await listDurableTasks("private-board", 50, controller.signal)).toBe(page);
  expect(apiClient.get).toHaveBeenCalledWith("/tasks", {
    signal: controller.signal,
    params: { table_id: "private-board", skip: "50", limit: "50" },
  });
});
