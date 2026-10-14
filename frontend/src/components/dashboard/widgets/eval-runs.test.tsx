import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { arm, evalRun } from "@/test-utils/eval-runs";
import { EvalRunsWidget } from "./eval-runs";

const recent = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-eval-runs", () => ({ useRecentEvalRuns: () => recent.value }));

const PERIOD: Period = { preset: "30d", from: "2026-09-14", to: "2026-10-14" };

function widget() {
  return render(
    <TooltipProvider>
      <EvalRunsWidget title="Eval runs" hint="Latest" period={PERIOD} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  recent.value = { runs: [], isLoading: false, error: null, refetch: vi.fn() };
});

describe("EvalRunsWidget", () => {
  it("counts the runs by status and lists each with its pass rate", () => {
    recent.value = {
      ...recent.value,
      runs: [
        evalRun(),
        evalRun({ id: "run-2", status: "running", arms: [arm({ role: "baseline" })] }),
      ],
    };
    widget();
    expect(screen.getByText("1 running")).toBeInTheDocument();
    expect(screen.getByText("1 completed")).toBeInTheDocument();
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: /refunds v3/ });
    expect(links[0]).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(screen.getByText("75%")).toBeInTheDocument();
    // A run with no candidate arm has no pass rate to show.
    expect(screen.getByText("—")).toBeInTheDocument();
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
