import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import { ImprovementHistory } from "./improvement-history";
import { ReadOnlyNote, ReadOnlyProvider, useReadOnly } from "./read-only";

const state = vi.hoisted(() => ({
  sessions: [] as Improvement[],
  isLoading: false,
  error: null as Error | null,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovements: () => ({
    sessions: state.sessions,
    isLoading: state.isLoading,
    error: state.error,
  }),
}));

beforeEach(() => {
  state.sessions = [];
  state.isLoading = false;
  state.error = null;
});

const started = {
  action: "improvement.started",
  at: "2026-10-24T12:00:00Z",
  stage: null,
  status: null,
  reason: null,
  actor_name: "Ada",
};

describe("ImprovementHistory", () => {
  it("lists each session with its decision, result, starter and cost, opening its wizard", () => {
    state.sessions = [
      { ...SESSION, id: "s1", status: "published", published_version: 3, timeline: [started] },
      {
        ...SESSION,
        id: "s2",
        status: "stopped",
        stop_reason: "budget",
        iterations: [
          {
            ...SESSION.iterations[0]!,
            verdict: "regression",
            verdict_detail: { fixed: 2, broken: 1 },
          },
        ],
      },
      { ...SESSION, id: "s3", status: "cancelled", best_iteration_id: null, iterations: [] },
    ];
    render(<ImprovementHistory agentId="a1" />);

    const [published, stopped, cancelled] = screen.getAllByRole("link");
    expect(published).toHaveAttribute("href", "/agents/a1/improve/s1");
    expect(published).toHaveTextContent("Published as version 3");
    expect(published).toHaveTextContent("Better: fixes 3, breaks nothing");
    expect(published).toHaveTextContent(/Started by Ada · \$0\.03/);
    expect(stopped).toHaveTextContent("Stopped");
    expect(stopped).toHaveTextContent("Mixed: fixes 2, breaks 1");
    expect(stopped).toHaveTextContent("The next complete step exceeds the remaining budget.");
    expect(stopped).toHaveTextContent(/^(?!.*Started by).*Cost \$0\.03/);
    expect(cancelled).toHaveTextContent("Cancelled");
    expect(cancelled).toHaveTextContent("Nothing measured");
  });

  it("names the last round when none was chosen, and a verdict without counts as none", () => {
    state.sessions = [
      {
        ...SESSION,
        best_iteration_id: null,
        iterations: [{ ...SESSION.iterations[0]!, verdict: "no_change", verdict_detail: null }],
      },
    ];
    render(<ImprovementHistory agentId="a1" />);
    expect(screen.getByRole("link")).toHaveTextContent("No reproducible change");
  });

  it("says so when the agent has had no session, and while reading or failing to", () => {
    const view = render(<ImprovementHistory agentId="a1" />);
    expect(screen.getByText("No improvement sessions yet.")).toBeInTheDocument();
    state.isLoading = true;
    view.rerender(<ImprovementHistory agentId="a1" />);
    expect(screen.queryByText("No improvement sessions yet.")).not.toBeInTheDocument();
    state.isLoading = false;
    state.error = new Error("read failed");
    view.rerender(<ImprovementHistory agentId="a1" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("No improvement sessions yet.")).not.toBeInTheDocument();
  });
});

describe("read-only", () => {
  function Probe() {
    return <p>{useReadOnly() ? "read" : "write"}</p>;
  }

  it("is off unless a page says why, and says why once", () => {
    const view = render(
      <>
        <Probe />
        <ReadOnlyNote />
      </>,
    );
    expect(screen.getByText("write")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    view.rerender(
      <ReadOnlyProvider value="finished">
        <Probe />
        <ReadOnlyNote />
      </ReadOnlyProvider>,
    );
    expect(screen.getByText("read")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/This improvement is finished/);
    view.rerender(
      <ReadOnlyProvider value="viewOnly">
        <ReadOnlyNote />
      </ReadOnlyProvider>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/needs edit access/);
  });
});
