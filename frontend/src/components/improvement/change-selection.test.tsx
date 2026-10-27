import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { hunk } from "@/test-utils/authoring";
import { SESSION } from "@/test-utils/improvement";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { ChangeSelection } from "./change-selection";
import { ReadOnlyProvider } from "./read-only";
const actions = vi.hoisted(() => ({
  estimateSelection: { mutateAsync: vi.fn(), isPending: false },
  checkSelection: { mutateAsync: vi.fn(), isPending: false },
  started: vi.fn(),
  evidenceLoaded: true,
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => actions,
  useImprovementEvidence: () => ({
    evidence: actions.evidenceLoaded
      ? {
          items: [
            { run_id: "r1", conversation_id: "c1", kind: "chat", question: "Can I return shoes?" },
            {
              run_id: "r2",
              conversation_id: null,
              kind: "train_eval",
              question: "Is delivery free?",
            },
            { run_id: "r4", conversation_id: null, kind: "train_eval", question: null },
          ],
        }
      : undefined,
  }),
}));
const QUOTE = { suggestions: 1, total_usd: "0.04", affordable: true, candidate_hash: "hash" };
const HUNKS = [hunk({ id: "h1" }), hunk({ id: "h2" })];
function Form({ session = SESSION, hunks = HUNKS }: { session?: Improvement; hunks?: Hunk[] }) {
  const [included, setIncluded] = useState(["h1", "h2"]);
  return (
    <ChangeSelection
      session={session}
      round={session.iterations[0]!}
      hunks={hunks}
      included={included}
      onChange={setIncluded}
      onStarted={actions.started}
    />
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  actions.evidenceLoaded = true;
  actions.estimateSelection.mutateAsync.mockResolvedValue(QUOTE);
  actions.checkSelection.mutateAsync.mockResolvedValue(SESSION);
  actions.checkSelection.isPending = actions.estimateSelection.isPending = false;
});
it("requires a fresh quote and explicit confirmation for the chosen changes", async () => {
  render(<Form />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(actions.checkSelection.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  expect(actions.estimateSelection.mutateAsync).toHaveBeenCalledWith({
    number: 1,
    hunkIds: ["h1"],
  });
  expect(await screen.findByText(/up to.*0.04.*estimate/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Confirm and check selected changes" }));
  expect(actions.checkSelection.mutateAsync).toHaveBeenCalledWith({
    number: 1,
    hunkIds: ["h1"],
    quote: QUOTE,
  });
  expect(actions.started).toHaveBeenCalledOnce();
});
it("invalidates the quote after a checkbox or proposal body changes", async () => {
  const view = render(<Form />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  await screen.findByRole("button", { name: "Confirm and check selected changes" });
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 1 in the test" }));
  expect(
    screen.queryByRole("button", { name: "Confirm and check selected changes" }),
  ).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 1 in the test" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  await screen.findByRole("button", { name: "Confirm and check selected changes" });
  view.rerender(
    <Form hunks={[hunk({ id: "h1", new_text: "Different instructions" }), hunk({ id: "h2" })]} />,
  );
  expect(
    screen.queryByRole("button", { name: "Confirm and check selected changes" }),
  ).not.toBeInTheDocument();
});
it("refuses an empty selection and disables controls during a paid check", async () => {
  const view = render(<Form />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 1 in the test" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Include change 2 in the test" }));
  expect(screen.getByText("Select at least one change to check.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Estimate checking selected changes" })).toBeDisabled();
  actions.checkSelection.isPending = true;
  view.rerender(<Form />);
  expect(screen.getByRole("checkbox", { name: "Include change 1 in the test" })).toBeDisabled();
});
it("keeps unaffordable checks disabled and shows refused requests", async () => {
  actions.estimateSelection.mutateAsync.mockResolvedValue({ ...QUOTE, affordable: false });
  render(<Form />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  expect(
    await screen.findByRole("button", { name: "Confirm and check selected changes" }),
  ).toBeDisabled();
  actions.estimateSelection.mutateAsync.mockRejectedValue(new Error("Unavailable"));
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});
it("does not advance the wizard if starting the check fails", async () => {
  actions.checkSelection.mutateAsync.mockRejectedValue(new Error("Changed estimate"));
  render(<Form />);
  await userEvent.click(screen.getByRole("button", { name: "Estimate checking selected changes" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm and check selected changes" }),
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(actions.started).not.toHaveBeenCalled();
});
it("shows decided hunks without offering them for another check", () => {
  render(
    <Form session={{ ...SESSION, status: "running" }} hunks={[hunk({ status: "accepted" })]} />,
  );
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Estimate checking selected changes" }),
  ).not.toBeInTheDocument();
});

it("keeps another request identity's measured changes readable without restarting its paid work", () => {
  render(<Form session={{ ...SESSION, can_restart: false }} />);
  expect(screen.getByRole("checkbox", { name: "Include change 1 in the test" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Estimate checking selected changes" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/original account and credentials/)).toBeInTheDocument();
});
it("says what each change should fix, and nothing for a change that does not say", () => {
  render(
    <Form
      hunks={[
        hunk({ id: "h1", expected_effect: "Refund questions get the 30-day window" }),
        hunk({ id: "h2", expected_effect: "" }),
      ]}
    />,
  );
  expect(screen.getAllByText("Should fix")).toHaveLength(1);
  expect(screen.getByText("Refund questions get the 30-day window")).toBeInTheDocument();
});
it("names each change by what it changes and bases it on conversations, not run ids", () => {
  render(
    <Form
      hunks={[
        hunk({
          id: "h1",
          kind: "instructions",
          evidence: [{ run_id: "r1", quote: "Refunds take 90 days" }],
        }),
        hunk({
          id: "h2",
          kind: "tool_override",
          tool_id: "t1",
          base_name: "lookup_order",
          evidence: [],
        }),
        hunk({
          id: "h3",
          kind: "spec_field",
          path: "model_profile_id",
          op: "set",
          applies: false,
          evidence: [],
        }),
      ]}
    />,
  );
  expect(screen.getByText("Instructions")).toBeInTheDocument();
  expect(screen.getByText("Tool description: lookup_order")).toBeInTheDocument();
  expect(screen.getByText("Model")).toBeInTheDocument();
  expect(screen.getByText("No longer fits the current instructions")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Conversation 1" })).toHaveAttribute("href", "/chat/c1");
  expect(screen.queryByText(/run r1/)).not.toBeInTheDocument();
  expect(
    screen.getAllByText("No test question or conversation is quoted for this change."),
  ).toHaveLength(2);
});
it("says where each quote came from: a test question or a conversation, and what was asked", () => {
  render(
    <Form
      hunks={[
        hunk({
          id: "h1",
          evidence: [
            { run_id: "r1", quote: "Refunds take 90 days", source: "conversation", number: 1 },
            { run_id: "r2", quote: "Delivery costs 5 euro", source: "test_question", number: 2 },
            { run_id: "r3", quote: "Kept before labels" },
            { run_id: "r4", quote: "A test question kept before labels" },
          ],
        }),
      ]}
    />,
  );
  const sources = screen.getAllByRole("listitem").map((item) => item.querySelector("p"));
  expect(sources.map((source) => source?.textContent)).toEqual([
    "Conversation 1: Can I return shoes?",
    "Test question 2: Is delivery free?",
    "Conversation 3",
    "Test question 4",
  ]);
  expect(screen.getByRole("link", { name: "Conversation 1" })).toHaveAttribute("href", "/chat/c1");
  expect(screen.queryByRole("link", { name: /Test question/ })).toBeNull();
});
it("quotes the evidence before its conversations are known, without a link", () => {
  actions.evidenceLoaded = false;
  render(
    <Form
      hunks={[hunk({ id: "h1", evidence: [{ run_id: "r1", quote: "Refunds take 90 days" }] })]}
    />,
  );
  expect(screen.getByText("Refunds take 90 days")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Conversation 1" })).toBeNull();
  expect(screen.getByText("Conversation 1")).toBeInTheDocument();
});
it("names a new skill, and a tool by its id when it has no name", () => {
  render(
    <Form
      hunks={[
        hunk({ id: "h1", kind: "create_skill", evidence: [] }),
        hunk({ id: "h2", kind: "tool_override", tool_id: "lookup", base_name: null, evidence: [] }),
      ]}
    />,
  );
  expect(screen.getByText("New skill")).toBeInTheDocument();
  expect(screen.getByText("Tool description: lookup")).toBeInTheDocument();
});

it("shows the changes but none of the choosing once the wizard is only read", () => {
  render(
    <ReadOnlyProvider value="finished">
      <Form />
    </ReadOnlyProvider>,
  );
  for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Estimate checking selected changes" }),
  ).not.toBeInTheDocument();
});
