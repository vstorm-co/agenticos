import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FLIP, comparison, evalRun } from "@/test-utils/eval-runs";
import type { EvalComparison, EvalRun, EvalSuiteCheck } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { CheckResult, CheckResults } from "./check-result";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  runs: {} as Record<string, unknown>,
  comparisons: {} as Record<string, unknown>,
  errors: {} as Record<string, Error>,
  enabled: {} as Record<string, boolean>,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-eval-runs", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-eval-runs")>()),
  useEvalRun: (runId: string) => ({ run: state.runs[runId], error: state.errors[runId] ?? null }),
  useEvalComparison: (runId: string, options: { enabled: boolean }) => {
    state.enabled[runId] = options.enabled;
    return { comparison: state.comparisons[runId] };
  },
}));

const suite: EvalSuiteCheck = {
  suite_id: "suite-1",
  name: "audit-smoke",
  suite_exists: true,
  status: "failed",
  reasons: [{ code: "regressions", value: 1, limit: 0, detail: null }],
};

function given(runId: string, run: Partial<EvalRun>, compared?: Partial<EvalComparison>) {
  state.runs[runId] = evalRun({ id: runId, ...run });
  if (compared) state.comparisons[runId] = comparison(compared);
}

function flip(input: string, overrides = {}) {
  return { ...FLIP, case_id: input, input, ...overrides };
}

beforeEach(() => {
  state.granted = [Perm.runsView];
  state.runs = {};
  state.comparisons = {};
  state.errors = {};
  state.enabled = {};
});

describe("CheckResult", () => {
  it("says what the suite would say and which question broke, linking the run", () => {
    given(
      "run-1",
      { suite_check: suite },
      { cases: [flip("Do you ship to Canada?")], regressions_confirmed: 1 },
    );
    render(<CheckResult agentId="agent-1" runId="run-1" />);

    const line = screen.getByRole("link", {
      name: "audit-smoke would fail: breaks “Do you ship to Canada?”",
    });
    expect(line).toHaveAttribute("href", "/agents/agent-1/evals/run-1");
    expect(line.className).toContain("text-destructive");
    expect(screen.getByRole("listitem")).toBeInTheDocument();
  });

  it("names the dataset when no suite judged it, quoting three breaks and counting the rest", () => {
    given(
      "run-1",
      { suite_check: null },
      {
        cases: ["A?", "B?", "C?", "D?", "E?"].map((input) => flip(input)),
        regressions_confirmed: 5,
        fixed_confirmed: 2,
        verdict: "mixed",
      },
    );
    render(<CheckResult agentId="agent-1" runId="run-1" />);

    expect(
      screen.getByRole("link", {
        name: "On refunds: breaks “A?”, “B?”, and “C?” and 2 more and fixes 2 cases",
      }),
    ).toBeInTheDocument();
  });

  it("leaves out a break the reruns did not confirm, and says when nothing held", () => {
    given(
      "run-1",
      {},
      {
        cases: [flip("Once?", { confirmed: false })],
        regressions_confirmed: 0,
        verdict: "no_difference",
      },
    );
    render(<CheckResult agentId="agent-1" runId="run-1" />);

    const line = screen.getByRole("link", { name: "On refunds: no reproducible change" });
    expect(line.className).toContain("text-muted-foreground");
  });

  it("says a fix in green, a passing suite in green, and a comparison that cannot be made", () => {
    given(
      "fixed",
      {},
      {
        cases: [flip("A?", { flip: "fixed" })],
        regressions_confirmed: 0,
        verdict: "better",
        fixed_confirmed: 1,
      },
    );
    given(
      "passed",
      { suite_check: { ...suite, status: "passed", reasons: [] } },
      { cases: [], regressions_confirmed: 0, verdict: "no_difference" },
    );
    given("invalid", {}, { verdict: "invalid", regressions_confirmed: 0 });
    render(
      <>
        <CheckResult agentId="agent-1" runId="fixed" />
        <CheckResult agentId="agent-1" runId="passed" />
        <CheckResult agentId="agent-1" runId="invalid" />
      </>,
    );

    expect(screen.getByRole("link", { name: "On refunds: fixes 1 case" }).className).toContain(
      "text-success",
    );
    expect(
      screen.getByRole("link", { name: "audit-smoke would pass: no reproducible change" })
        .className,
    ).toContain("text-success");
    expect(
      screen.getByRole("link", { name: "On refunds: the two sides cannot be compared" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).toBeNull();
  });

  it("says a check is still running, or how it ended, without reading its comparison", () => {
    given("live", { status: "running" });
    given("stopped", { status: "cancelled" });
    render(
      <>
        <CheckResult agentId="agent-1" runId="live" />
        <CheckResult agentId="agent-1" runId="stopped" />
      </>,
    );

    expect(screen.getByRole("link", { name: "Checking on refunds…" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", {
        name: "The check on refunds was stopped before it reached a verdict.",
      }),
    ).toBeInTheDocument();
    expect(state.enabled).toEqual({ live: false, stopped: false });
  });

  it("says a check could not be read, and nothing while it loads", () => {
    state.errors["broken"] = new Error("boom");
    given("waiting", {});
    const { container } = render(<CheckResult agentId="agent-1" runId="loading" />);
    expect(container).toBeEmptyDOMElement();

    render(
      <>
        <CheckResult agentId="agent-1" runId="broken" />
        <CheckResult agentId="agent-1" runId="waiting" />
      </>,
    );
    expect(screen.getByText("Could not read this check.")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("CheckResults", () => {
  it("states the latest three checks for a reader of runs, and nothing for anybody else", () => {
    for (const runId of ["c1", "c2", "c3", "c4"]) {
      given(
        runId,
        { dataset_name: runId },
        { verdict: "no_difference", regressions_confirmed: 0, cases: [] },
      );
    }
    const { rerender } = render(
      <CheckResults agentId="agent-1" runIds={["c1", "c2", "c3", "c4"]} />,
    );
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "On c2: no reproducible change",
      "On c3: no reproducible change",
      "On c4: no reproducible change",
    ]);

    state.granted = [];
    rerender(<CheckResults agentId="agent-1" runIds={["c1"]} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
