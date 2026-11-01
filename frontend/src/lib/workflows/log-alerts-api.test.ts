import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { createLogAlert, deleteLogAlert, listLogAlerts, updateLogAlert } from "./log-alerts-api";
import type { LogAlertInput } from "./types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => vi.clearAllMocks());

const INPUT: LogAlertInput = {
  name: "Failures",
  outcomes: ["error"],
  node_instance_id: null,
  message_contains: null,
  threshold: 5,
  window_minutes: 15,
  audience: ["admins"],
  user_ids: [],
  enabled: true,
};

describe("log-alerts-api", () => {
  it("lists the rules of a workflow, unwrapped from the list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "r1" }] });
    expect(await listLogAlerts("wf")).toEqual([{ id: "r1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf/log-alerts");
  });

  it("creates, changes and deletes a rule under the workflow", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r1" });
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1" });
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);

    await createLogAlert("wf", INPUT);
    await updateLogAlert("wf", "r1", { enabled: false });
    await deleteLogAlert("wf", "r1");

    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf/log-alerts", INPUT);
    expect(apiClient.patch).toHaveBeenCalledWith("/workflows/wf/log-alerts/r1", {
      enabled: false,
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/workflows/wf/log-alerts/r1");
  });
});
