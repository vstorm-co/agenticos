import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import { CheckRunVerdicts } from "./check-run-verdicts";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  runs: {} as Record<string, unknown>,
  read: [] as string[],
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRun: (runId: string) => {
    state.read.push(runId);
    return { run: state.runs[runId] };
  },
}));

const judged = {
  suite_id: "suite-1",
  name: "Nightly",
  suite_exists: true,
  status: "passed",
  reasons: [],
};

beforeEach(() => {
  state.granted = [Perm.runsView];
  state.read = [];
  state.runs = {
    "on-dataset": { suite_check: null },
    "on-suite": { suite_check: judged },
    running: { suite_check: { ...judged, status: null } },
  };
});

describe("CheckRunVerdicts", () => {
  it("shows the suite's verdict beside the check that ran on it, and nothing for the rest", () => {
    render(<CheckRunVerdicts agentId="agent-1" runIds={["on-dataset", "on-suite", "running"]} />);

    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("run 2")).toBeInTheDocument();
    expect(screen.queryByText("run 1")).toBeNull();
    expect(screen.queryByText("run 3")).toBeNull();
  });

  it("reads only the latest checks, however many the batch keeps", () => {
    const runIds = ["a", "b", "c", "d", "e"];
    state.runs = Object.fromEntries(runIds.map((id) => [id, { suite_check: judged }]));
    render(<CheckRunVerdicts agentId="agent-1" runIds={runIds} />);

    expect(screen.queryByText("run 2")).toBeNull();
    expect(["run 3", "run 4", "run 5"].map((text) => screen.getByText(text))).toHaveLength(3);
    expect(state.read).toEqual(["c", "d", "e"]);
  });

  it("is not there for a caller who may not read runs", () => {
    state.granted = [];
    const { container } = render(<CheckRunVerdicts agentId="agent-1" runIds={["on-suite"]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
