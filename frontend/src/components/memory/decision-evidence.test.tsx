import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import { beforeEach, expect, it, vi } from "vitest";
import { reviewDecisionCase, type MemoryClaim } from "@/lib/memory-api";
import type { Dataset } from "@/types/datasets";
import { DecisionEvidence } from "./decision-evidence";

const state = vi.hoisted(() => ({
  canAdd: true,
  error: null as Error | null,
  refetch: vi.fn(),
  target: undefined as unknown,
  editable: [] as unknown[],
  push: vi.fn(),
  remember: vi.fn(),
  choose: vi.fn(),
}));
vi.mock("@/lib/memory-api", () => ({ reviewDecisionCase: vi.fn() }));
vi.mock("@/components/datasets/use-dataset-target", () => ({
  useCanAddToDataset: () => state.canAdd,
  useDatasetTarget: () => ({
    editable: state.editable,
    isLoading: false,
    error: state.error,
    refetch: state.refetch,
    search: null,
    target: state.target,
    choose: state.choose,
    remember: state.remember,
  }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));

const decisions = { id: "d", name: "Decisions" } as Dataset;
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
  vi.mocked(toast.success).mockReset();
  state.canAdd = true;
  state.error = null;
  state.refetch.mockReset();
  state.choose.mockReset();
  state.target = decisions;
  state.editable = [decisions];
  state.push.mockReset();
  state.remember.mockReset();
});
it("adds the case to the chosen dataset only after a human reviews the editable text", async () => {
  vi.mocked(reviewDecisionCase).mockResolvedValue({} as never);
  mount();
  expect(screen.getByText("Wait; Escalate")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  const add = screen.getByRole("button", { name: "Add reviewed case" });
  expect(add).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.type(screen.getByRole("textbox", { name: "Input to evaluate" }), " again");
  expect(add).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(add);
  await waitFor(() =>
    expect(reviewDecisionCase).toHaveBeenCalledWith(
      "c",
      "d",
      "Delivery overdue again",
      "Ask the owner",
    ),
  );
  expect(state.remember).toHaveBeenCalledWith(decisions);
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const [message, options] = vi.mocked(toast.success).mock.calls[0]! as unknown as [
    string,
    { action: { label: string; onClick: () => void } },
  ];
  expect([message, options.action.label]).toEqual(["Added to Decisions", "Open dataset"]);
  options.action.onClick();
  expect(state.push).toHaveBeenCalledWith("/datasets/d?tab=cases");
});
it("cannot add before a dataset is chosen", async () => {
  state.target = undefined;
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "Add reviewed case" })).toBeDisabled();
});
it("keeps a refused add open with an error", async () => {
  vi.mocked(reviewDecisionCase).mockRejectedValue(new Error("Add refused"));
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "Add reviewed case" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("offers nothing to somebody who may add to no dataset", () => {
  state.canAdd = false;
  mount();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("does not offer historical decisions", () => {
  mount({ ...claim, status: "retracted" });
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("requires fresh consent after changing the reference and allows dismissal", async () => {
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.type(screen.getByRole("textbox", { name: "Expected answer" }), " today");
  expect(screen.getByRole("button", { name: "Add reviewed case" })).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(reviewDecisionCase).not.toHaveBeenCalled();
});
it("has no evidence to add when the entry is not a decision", () => {
  mount({ ...claim, episode: undefined });
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("starts from the correction and stays open while the case is being added", async () => {
  vi.mocked(reviewDecisionCase).mockReturnValue(new Promise(() => {}));
  mount({ ...claim, episode: { ...claim.episode!, correction: "Escalate after no reply" } });
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  expect(screen.getByRole("textbox", { name: "Expected answer" })).toHaveValue(
    "Escalate after no reply",
  );
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("button", { name: "Add reviewed case" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("asks for consent again once another dataset is chosen", async () => {
  const other = { id: "o", name: "Other" } as Dataset;
  state.editable = [decisions, other];
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  await userEvent.click(screen.getByRole("checkbox"));
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: "Other" }));
  expect(state.choose).toHaveBeenCalledWith("o");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Add reviewed case" })).toBeDisabled();
});
it("says when the datasets could not be listed and offers a retry", async () => {
  state.error = new Error("Listing failed");
  state.target = undefined;
  mount();
  await userEvent.click(screen.getByRole("button", { name: "Add as an Improve case" }));
  expect(screen.getByRole("alert")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalled();
});
