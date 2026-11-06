import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { reviewDecisionCase, type MemoryClaim } from "@/lib/memory-api";
import { DecisionEvidence } from "./decision-evidence";
vi.mock("@/lib/memory-api", () => ({ reviewDecisionCase: vi.fn() }));
const claim: MemoryClaim = {
  id: "c",
  agent_id: "a",
  agent_name: "Planner",
  scope: "agent",
  subject: "delivery",
  statement: "Ask the owner",
  kind: "decision",
  origin: "agent",
  status: "current",
  observed_at: "2026-11-04T00:00:00Z",
  effective_from: null,
  effective_to: null,
  supersedes_id: null,
  derived_from_count: 0,
  episode: {
    situation: "Delivery overdue",
    choice: "Ask the owner",
    alternatives: ["Wait", "Escalate"],
    expected_outcome: "New deadline",
    actual_outcome: null,
    correction: null,
  },
};
function mount(data = claim) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      <DecisionEvidence claim={data} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.mocked(reviewDecisionCase).mockReset();
  URL.createObjectURL = vi.fn(() => "blob:case");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
it("shows evidence and exports only after a human reviews the editable case", async () => {
  vi.mocked(reviewDecisionCase).mockResolvedValue({
    input: "Delivery overdue",
    reference_answer: "Ask the owner",
    tags: ["decision-episode"],
    note: "source",
  });
  mount();
  expect(screen.getByText("Wait; Escalate")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Prepare Improve case" }));
  const download = screen.getByRole("button", { name: "Download reviewed case" });
  expect(download).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.type(screen.getByRole("textbox", { name: "Input to evaluate" }), " again");
  expect(download).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(download);
  await waitFor(() =>
    expect(reviewDecisionCase).toHaveBeenCalledWith("c", "Delivery overdue again", "Ask the owner"),
  );
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:case"));
});
it("keeps a refused export open with an error", async () => {
  vi.mocked(reviewDecisionCase).mockRejectedValue(new Error("Export refused"));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Prepare Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "Download reviewed case" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("does not export historical decisions", () => {
  mount({ ...claim, status: "retracted" });
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("requires fresh consent after changing the reference and allows dismissal", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Prepare Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.type(screen.getByRole("textbox", { name: "Expected answer" }), " today");
  expect(screen.getByRole("button", { name: "Download reviewed case" })).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(reviewDecisionCase).not.toHaveBeenCalled();
});
it("has no evidence to export when the entry is not a decision", () => {
  mount({ ...claim, episode: undefined });
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
