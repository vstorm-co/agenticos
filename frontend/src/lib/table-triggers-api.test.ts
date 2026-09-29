import { beforeEach, expect, it, vi } from "vitest";

import {
  createTableTrigger,
  deleteTableTrigger,
  listTableTriggerAdmissions,
  listTableTriggers,
  updateTableTrigger,
} from "./table-triggers-api";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

it("reaches every trigger route under the table", async () => {
  await listTableTriggers("tbl");
  expect(apiClient.get).toHaveBeenLastCalledWith("/tables/tbl/triggers");

  await createTableTrigger("tbl", { workflow_id: "wf" });
  expect(apiClient.post).toHaveBeenCalledWith("/tables/tbl/triggers", { workflow_id: "wf" });

  await updateTableTrigger("tbl", "t1", { is_active: false });
  expect(apiClient.patch).toHaveBeenCalledWith("/tables/tbl/triggers/t1", { is_active: false });

  await deleteTableTrigger("tbl", "t1");
  expect(apiClient.delete).toHaveBeenCalledWith("/tables/tbl/triggers/t1");

  await listTableTriggerAdmissions("tbl", "t1");
  expect(vi.mocked(apiClient.get).mock.lastCall?.[0]).toContain(
    "/tables/tbl/triggers/t1/admissions",
  );
});
