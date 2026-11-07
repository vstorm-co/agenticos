import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { suiteResult, suiteSummary } from "@/test-utils/eval-suites";
import type { PromotionGate } from "@/types/promotion-gate";
import { EnvironmentGuardStatus } from "./environment-guard-status";

const state = vi.hoisted(() => ({
  gate: undefined as PromotionGate | undefined,
  error: null as Error | null,
}));
const read = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-promotion-gate", () => ({
  usePromotionGate: (...args: unknown[]) => {
    read(...args);
    return state;
  },
}));
const base = {
  agentId: "a1",
  environmentId: "production",
  versionId: "v2",
  version: 2,
  servedVersion: 1,
  canReadRuns: true,
  onPromote: vi.fn(),
};

beforeEach(() => {
  state.gate = undefined;
  state.error = null;
  vi.clearAllMocks();
});

function failedGate(): PromotionGate {
  return {
    environment_id: "production",
    environment_name: "production",
    version_id: "v2",
    version: 2,
    guarded: true,
    passing: false,
    can_override: false,
    guards: [
      {
        suite_id: "s1",
        suite_name: "Refund smoke",
        state: "failed",
        paused_reason: null,
        result: suiteResult({
          status: "failed",
          eval_run_id: "r1",
          summary: suiteSummary({
            pass_rate: 0.67,
            reasons: [{ code: "pass_rate_below", value: 0.67, limit: 0.8, detail: null }],
          }),
        }),
      },
    ],
  };
}

describe("EnvironmentGuardStatus", () => {
  it("shows the failed guard and links its run while the environment stays on v1", () => {
    state.gate = failedGate();
    render(<EnvironmentGuardStatus {...base} />);
    expect(screen.getByText("Stays on v1")).toBeInTheDocument();
    expect(screen.getByText(/Refund smoke: Failed/)).toBeInTheDocument();
    expect(screen.getByText(/67%/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the check" })).toHaveAttribute(
      "href",
      "/agents/a1/evals/r1",
    );
    expect(screen.queryByText(/Waiting for its evals/)).not.toBeInTheDocument();
  });
  it("shows who corrected the grading and requires a person to promote", async () => {
    const failed = failedGate();
    state.gate = {
      ...failed,
      passing: true,
      guards: [
        {
          ...failed.guards[0]!,
          state: "passed",
          result: suiteResult({
            eval_run_id: "r1",
            summary: suiteSummary({
              review: {
                by_user_id: "u1",
                by_name: "Ada",
                at: "2026-10-24T12:00:00Z",
                previous_verdict: "failed",
                verdict: "passed",
                undo: false,
              },
            }),
          }),
        },
      ],
    };
    render(<EnvironmentGuardStatus {...base} />);
    expect(screen.getByText(/Re-evaluated after review by Ada/)).toBeInTheDocument();
    expect(screen.getByText("v2 is ready for a person to promote")).toBeInTheDocument();
    expect(base.onPromote).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Review promotion" }));
    expect(base.onPromote).toHaveBeenCalledOnce();
  });
  it("disables the query and shows no run details without runs:view", () => {
    state.gate = failedGate();
    render(<EnvironmentGuardStatus {...base} canReadRuns={false} />);
    expect(read).toHaveBeenCalledWith("a1", "production", "v2", { enabled: false });
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText(/Refund smoke/)).not.toBeInTheDocument();
  });
});

it("distinguishes loading from a failed status read and offers a way to retry", async () => {
  const { rerender } = render(<EnvironmentGuardStatus {...base} />);
  expect(screen.getByRole("status")).toBeInTheDocument();
  state.error = new Error("offline");
  rerender(<EnvironmentGuardStatus {...base} />);
  await userEvent.click(screen.getByRole("button", { name: "Read guard results" }));
  expect(base.onPromote).toHaveBeenCalledOnce();
});
