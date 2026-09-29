import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import {
  getWorkflowExposure,
  rotateWorkflowExposureSecret,
  updateWorkflowExposure,
} from "./exposures-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

beforeEach(() => vi.clearAllMocks());

describe("exposures-api", () => {
  it("reads and writes one workflow's exposure under its own path", async () => {
    await getWorkflowExposure("wf");
    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf/exposure");

    await updateWorkflowExposure("wf", "e1", { is_active: false });
    expect(apiClient.patch).toHaveBeenCalledWith("/workflows/wf/exposures/e1", {
      is_active: false,
    });

    await rotateWorkflowExposureSecret("wf", "e1");
    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf/exposures/e1/rotate-secret");
  });
});
