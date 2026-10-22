import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { arm, evalRun } from "@/test-utils/eval-runs";
import { EvalRunsWidget } from "./eval-runs";

const recent = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-eval-runs", () => ({ useRecentEvalRuns: () => recent.value }));
const access = vi.hoisted(() => ({ agents: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => access.agents }),
}));
vi.mock("@/hooks", () => ({
  useAgents: ({ enabled }: { enabled: boolean }) => ({
    agents: enabled ? [{ id: "agent-1", name: "Refund desk" }] : [],
  }),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-14", to: "2026-10-14" };

function widget() {
  return render(
    <TooltipProvider>
      <EvalRunsWidget title="Eval runs" hint="Latest" period={PERIOD} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  access.agents = true;
  recent.value = { runs: [], isLoading: false, error: null, refetch: vi.fn() };
});

describe("EvalRunsWidget", () => {
  it("counts the runs by status and lists each with its agent, verdict and pass rate", () => {
    recent.value = {
      ...recent.value,
      runs: [
        evalRun({
          outcome: {
            candidate_arm_id: "arm-1",
            verdict: "worse",
            baseline: null,
            regressions_confirmed: 2,
            fixed_confirmed: 0,
            candidate_pass_rate: 0.75,
            baseline_pass_rate: 1,
            overall: null,
            candidate_first_pass_rate: null,
            baseline_first_pass_rate: null,
            candidate_undecided: 0,
          },
        }),
        evalRun({ id: "run-2", status: "running", arms: [arm({ role: "baseline" })] }),
      ],
    };
    widget();
    expect(screen.getByText("1 running")).toBeInTheDocument();
    expect(screen.getByText("1 completed")).toBeInTheDocument();
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: /^Refund desk · v7/ });
    expect(links[0]).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(screen.getByText("Breaks 2")).toBeInTheDocument();
    expect(screen.getByText("gpt-4.1 75%")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    // Activity lists each case's runs, not these: the card links only the runs themselves.
    expect(screen.queryByRole("link", { name: /Activity/ })).toBeNull();
  });

  it("starts a row at what was tested for who may not see agents", () => {
    access.agents = false;
    recent.value = { ...recent.value, runs: [evalRun()] };
    widget();
    expect(screen.getByRole("link", { name: /^v7/ })).toBeInTheDocument();
  });

  it("says when there is nothing yet", () => {
    widget();
    expect(screen.getByText("No eval runs yet")).toBeInTheDocument();
  });

  it("offers a retry when the runs could not be read", async () => {
    const refetch = vi.fn();
    recent.value = { runs: [], isLoading: false, error: new Error("boom"), refetch };
    widget();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a placeholder while loading", () => {
    recent.value = { ...recent.value, isLoading: true };
    const { container } = widget();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });
});
