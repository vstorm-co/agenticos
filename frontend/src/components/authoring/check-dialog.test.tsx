import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { evalRun } from "@/test-utils/eval-runs";
import type { EvalRunEstimate } from "@/types/eval-runs";
import { CheckDialog } from "./check-dialog";

vi.mock("@/hooks/use-eval-runs", () => ({
  useEveryDataset: () => ({ datasets: [{ id: "ds-1", name: "Refund cases" }] }),
  useEveryAgent: () => ({ agents: [{ id: "agent-2", name: "Clerk" }] }),
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

describe("CheckDialog", () => {
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
    await pick("Dataset", "Refund cases");
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
    await pick("Agent that uses the skill", "Clerk");
    await pick("Dataset", "Refund cases");
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
    await pick("Dataset", "Refund cases");
    await screen.findByText("estimate 0.20");
    await userEvent.click(screen.getByRole("button", { name: "Start the check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Every case is evidence");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
