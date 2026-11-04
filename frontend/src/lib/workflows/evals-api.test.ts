import { describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import { createStepEval, deleteStepEval, listStepEvals, tryStepEvals } from "./evals-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

describe("evals-api", () => {
  it("reaches each route of a step's evals", async () => {
    const input = {
      name: "Refund",
      run_input: {},
      outputs: {},
      expectation: { kind: "equals" as const, field: "category", value: "billing" },
    };

    await listStepEvals("wf", "n1");
    await createStepEval("wf", "n1", input);
    await deleteStepEval("wf", "e1");
    await tryStepEvals("wf", "n1");

    expect(apiClient.get).toHaveBeenCalledWith("/workflows/wf/steps/n1/evals");
    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf/steps/n1/evals", input);
    expect(apiClient.delete).toHaveBeenCalledWith("/workflows/wf/evals/e1");
    expect(apiClient.post).toHaveBeenCalledWith("/workflows/wf/steps/n1/eval-runs");
  });
});
