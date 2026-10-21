import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { evalRun } from "@/test-utils/eval-runs";
import type { EvalRunEstimate } from "@/types/eval-runs";
import { CheckDialog } from "./check-dialog";

vi.mock("@/hooks/use-eval-runs", () => ({
  useEveryDataset: () => ({ datasets: [{ id: "ds-1", name: "Refund cases" }] }),
  useEveryAgent: () => ({
    agents: [
      { id: "agent-2", name: "Clerk" },
      { id: "agent-3", name: "Teller" },
    ],
  }),
}));
const suites = vi.hoisted(() => ({
  forAgent: {} as Record<string, { id: string; name: string; dataset_name: string | null }[]>,
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useAgentEvalSuites: (agentId: string) => ({ suites: suites.forAgent[agentId] ?? [] }),
}));
vi.mock("@/components/evals/estimate-summary", () => ({
  EstimateSummary: ({ estimate }: { estimate: EvalRunEstimate }) => (
    <p>{`estimate ${estimate.total_usd}`}</p>
  ),
}));

const ESTIMATE = { total_usd: "0.20", affordable: true } as EvalRunEstimate;

async function pick(label: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  suites.forAgent = {};
});

describe("CheckDialog", () => {
  it("checks against one of the agent's suites, which brings its own dataset", async () => {
    suites.forAgent = {
      "agent-1": [
        { id: "suite-1", name: "Nightly", dataset_name: "Refund cases" },
        { id: "suite-2", name: "Hidden", dataset_name: null },
      ],
    };
    const estimate = vi.fn().mockResolvedValue(ESTIMATE);
    render(
      <CheckDialog
        agentId="agent-1"
        estimate={estimate}
        start={vi.fn()}
        onStarted={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    await pick("Check against", "Nightly · Refund cases");
    expect(await screen.findByText("estimate 0.20")).toBeInTheDocument();
    expect(estimate).toHaveBeenCalledWith({ suite_id: "suite-1" });
  });

  it("forgets a suite when the skill change moves to another agent", async () => {
    suites.forAgent = { "agent-2": [{ id: "suite-9", name: "Nightly", dataset_name: null }] };
    const estimate = vi.fn().mockResolvedValue(ESTIMATE);
    render(
      <CheckDialog
        agentId={null}
        proposalId="change-1"
        estimate={estimate}
        start={vi.fn()}
        onStarted={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    await pick("Agent that uses the skill", "Clerk");
    await pick("Check against", "Nightly");
    await waitFor(() =>
      expect(estimate).toHaveBeenCalledWith({
        suite_id: "suite-9",
        agent_id: "agent-2",
        proposal_id: "change-1",
      }),
    );
    await pick("Agent that uses the skill", "Teller");
    expect(screen.getByRole("combobox", { name: "Check against" })).toHaveTextContent(
      "Pick a suite or a dataset",
    );
  });

  it("prices the check for the chosen dataset and starts it", async () => {
    const estimate = vi.fn().mockResolvedValue(ESTIMATE);
    const start = vi.fn().mockResolvedValue(evalRun());
    const onStarted = vi.fn();
    render(
      <CheckDialog
        agentId="agent-1"
        estimate={estimate}
        start={start}
        onStarted={onStarted}
        onOpenChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Start the check" })).toBeDisabled();
    expect(screen.getByText(/against the draft as it would be/)).toBeInTheDocument();
    await pick("Check against", "Refund cases");
    expect(await screen.findByText("estimate 0.20")).toBeInTheDocument();
    expect(estimate).toHaveBeenCalledWith({ dataset_id: "ds-1" });
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
  });

  it("asks a skill change for the agent it runs on, and shows a refusal", async () => {
    const estimate = vi.fn().mockRejectedValue(new Error("Clerk does not use refunds"));
    render(
      <CheckDialog
        agentId={null}
        proposalId="change-1"
        estimate={estimate}
        start={vi.fn()}
        onStarted={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    // Both sides run the agent's published version; only the skill's body differs.
    expect(screen.getByText(/only the skill's body different/)).toBeInTheDocument();
    expect(screen.queryByText(/against the draft/)).toBeNull();
    await pick("Agent that uses the skill", "Clerk");
    await pick("Check against", "Refund cases");
    expect(await screen.findByRole("alert")).toHaveTextContent("Clerk does not use refunds");
    expect(estimate).toHaveBeenCalledWith({
      dataset_id: "ds-1",
      agent_id: "agent-2",
      proposal_id: "change-1",
    });
  });

  it("shows a refused start and cancels", async () => {
    const onOpenChange = vi.fn();
    render(
      <CheckDialog
        agentId="agent-1"
        estimate={vi.fn().mockResolvedValue(ESTIMATE)}
        start={vi.fn().mockRejectedValue(new Error("Every case is evidence"))}
        onStarted={vi.fn()}
        onOpenChange={onOpenChange}
      />,
    );
    await pick("Check against", "Refund cases");
    await screen.findByText("estimate 0.20");
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Every case is evidence");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
