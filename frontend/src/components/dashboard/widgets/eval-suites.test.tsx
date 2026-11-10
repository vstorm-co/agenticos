import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { evalSuite, suiteResult } from "@/test-utils/eval-suites";
import { suiteState } from "@/components/evals/suites/suite-format";
import { EvalSuitesWidget } from "./eval-suites";

const visible = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("@/hooks/use-eval-suites", () => ({ useVisibleEvalSuites: () => visible.value }));

const PERIOD: Period = { preset: "30d", from: "2026-09-19", to: "2026-10-19" };

function widget() {
  return render(
    <TooltipProvider>
      <EvalSuitesWidget title="Eval suites" hint="Suites" period={PERIOD} />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  visible.value = { suites: [], isLoading: false, error: null, refetch: vi.fn() };
});

describe("suiteState", () => {
  it("reads a suite by its last result, and a paused one as paused", () => {
    expect(suiteState(evalSuite())).toBe("passing");
    expect(suiteState(evalSuite({ is_active: false }))).toBe("paused");
    expect(suiteState(evalSuite({ last_result: null }))).toBe("waiting");
    // Anything the server marks alerting - what the owner is notified of - is failing.
    for (const status of ["failed", "error", "skipped", "inconclusive"] as const) {
      expect(suiteState(evalSuite({ last_result: suiteResult({ status }) }))).toBe("failing");
    }
    for (const status of ["pending", "running"] as const) {
      expect(suiteState(evalSuite({ last_result: suiteResult({ status }) }))).toBe("waiting");
    }
  });
});

describe("EvalSuitesWidget", () => {
  it("counts the suites by how they stand and lists the failing ones first", () => {
    visible.value = {
      ...visible.value,
      suites: [
        evalSuite({ id: "a", name: "Fine" }),
        evalSuite({ id: "b", name: "Broken", last_result: suiteResult({ status: "failed" }) }),
        evalSuite({ id: "c", name: "New", last_result: null }),
      ],
    };
    widget();

    expect(screen.getByText("1 failing")).toBeInTheDocument();
    expect(screen.getByText("1 passing")).toBeInTheDocument();
    expect(screen.getByText("1 waiting for a first run")).toBeInTheDocument();
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Broken · ClerkFailed",
      "New · ClerkNo result yet",
      "Fine · ClerkPassed",
    ]);
    expect(links[0]).toHaveAttribute("href", "/agents/agent-1?tab=evals");
  });

  it("says in one line that there are no suites yet", () => {
    widget();
    expect(
      screen.getByText("No suites yet. Set one up on an agent's Evals tab."),
    ).toBeInTheDocument();
  });

  it("waits, and offers to read again when the suites could not be read", async () => {
    visible.value = { ...visible.value, isLoading: true };
    const { rerender } = widget();
    expect(screen.queryByRole("link")).toBeNull();

    const refetch = vi.fn();
    visible.value = { suites: [], isLoading: false, error: new Error("boom"), refetch };
    rerender(
      <TooltipProvider>
        <EvalSuitesWidget title="Eval suites" hint="Suites" period={PERIOD} />
      </TooltipProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
