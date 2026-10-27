import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { ContinuationEstimate } from "@/types/improvement";
import { ContinueSession, continuation } from "./continue-session";

const state = vi.hoisted(() => ({ estimate: vi.fn(), start: vi.fn(), discard: vi.fn() }));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    estimateContinuation: { mutateAsync: state.estimate },
    continueSession: { mutateAsync: state.start },
    discard: { mutateAsync: state.discard },
  }),
}));
const QUOTE: ContinuationEstimate = {
  mode: "next_round",
  number: 2,
  total_usd: "0.04",
  budget_usd: "1",
  affordable: true,
  candidate_hash: "hash",
};
beforeEach(() => {
  vi.clearAllMocks();
  state.estimate.mockResolvedValue(QUOTE);
  state.start.mockResolvedValue({});
  state.discard.mockResolvedValue({});
});

it("estimates and confirms another round separately without publishing", async () => {
  const started = vi.fn();
  render(<ContinueSession session={SESSION} onStarted={started} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(await screen.findByText(/Attempt 2 of 3.*0.04.*estimate/)).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm the estimate and continue" }));
  expect(state.start).toHaveBeenCalledWith(QUOTE);
  expect(started).toHaveBeenCalledOnce();
});
it("offers the limit in cents, and prices only the step a press starts", async () => {
  render(<ContinueSession session={{ ...SESSION, budget_usd: "0.850000" }} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  expect(screen.getByLabelText("Session spending limit (USD)")).toHaveValue("0.85");
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "0.0034" });
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(state.estimate).toHaveBeenCalledWith("0.85");
  expect(
    await screen.findByText(
      "Attempt 2 of 3: up to $0.0034 (estimate) to write the changes; testing them is priced at the next step.",
    ),
  ).toBeInTheDocument();
});
it("hands a new attempt's helper the person's note, trimmed, and only that attempt", async () => {
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  const note = screen.getByRole("textbox", { name: "Note for the helper (optional)" });
  expect(note).toHaveAttribute("maxLength", "2000");
  await userEvent.type(note, "  Keep refunds short  ");
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  );
  expect(state.start).toHaveBeenCalledWith({ ...QUOTE, note: "Keep refunds short" });
});
it("sends no note that is only spaces, and offers none when a failed step is retried", async () => {
  const view = render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.type(
    screen.getByRole("textbox", { name: "Note for the helper (optional)" }),
    "   ",
  );
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  );
  expect(state.start).toHaveBeenCalledWith(QUOTE);
  view.unmount();
  render(
    <ContinueSession
      session={{ ...SESSION, status: "failed", stage: "proposing" }}
      onStarted={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Retry this step within the spending limit" }),
  );
  expect(
    screen.queryByRole("textbox", { name: "Note for the helper (optional)" }),
  ).not.toBeInTheDocument();
});
it("requires another estimate after changing the spending limit", async () => {
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await screen.findByRole("button", { name: "Confirm the estimate and continue" });
  await userEvent.clear(screen.getByLabelText("Session spending limit (USD)"));
  expect(screen.getByRole("button", { name: "Estimate continuing the session" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Confirm the estimate and continue" }),
  ).not.toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Session spending limit (USD)"), "2");
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(state.estimate).toHaveBeenLastCalledWith("2");
});
it("does not confirm an unaffordable continuation", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, affordable: false });
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  ).toBeDisabled();
  expect(screen.getByText(/does not fit the selected limit/)).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
});
it("offers a priced retry for a failed step without consuming another round", async () => {
  render(
    <ContinueSession
      session={{ ...SESSION, status: "failed", stage: "proposing" }}
      onStarted={vi.fn()}
    />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Retry this step within the spending limit" }),
  );
  expect(screen.getByRole("button", { name: "Estimate continuing the session" })).toBeEnabled();
  expect(state.start).not.toHaveBeenCalled();
});
it("offers raising a budget before resuming a stopped check", async () => {
  render(
    <ContinueSession
      session={{ ...SESSION, status: "stopped", stage: "evaluating", stop_reason: "budget" }}
      onStarted={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Raise the limit and continue" }));
  expect(screen.getByLabelText("Session spending limit (USD)")).toHaveValue("1.00");
});
it.each([
  [
    { reason: "nothing_to_learn" as const },
    /fixed every question it learns from, so another attempt has nothing to learn from/,
  ],
  [{ reason: "missing_holdout" as const, needed: 2 }, /2 more questions kept aside/],
])("says why another attempt is not offered: %o", (blocked, why) => {
  const session = { ...SESSION, status: "ready" as const, try_again_blocked: blocked };
  expect(continuation(session).canContinue).toBe(false);
  render(<ContinueSession session={session} onStarted={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent(why);
  expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
});
it("keeps paid restarts with their original requester", () => {
  render(
    <ContinueSession
      session={{ ...SESSION, can_restart: false, can_discard: false }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Discard" })).not.toBeInTheDocument();
  expect(screen.getByText(/original account and credentials/)).toBeInTheDocument();
});
it("shows an explicit stopped state at the round limit", () => {
  render(<ContinueSession session={{ ...SESSION, max_iterations: 1 }} onStarted={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
  expect(screen.getByText(/No further paid attempt/)).toBeInTheDocument();
});
it("is absent while work is running or already accepted", () => {
  const view = render(
    <ContinueSession session={{ ...SESSION, status: "running" }} onStarted={vi.fn()} />,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  view.rerender(
    <ContinueSession session={{ ...SESSION, status: "published" }} onStarted={vi.fn()} />,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("shows a failed estimate without starting work", async () => {
  state.estimate.mockRejectedValue(new Error("Quote unavailable"));
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(state.start).not.toHaveBeenCalled();
});
it("discards only after the normal confirmation dialog", async () => {
  const started = vi.fn();
  render(<ContinueSession session={SESSION} onStarted={started} />);
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  const dialog = screen.getByRole("dialog");
  expect(state.discard).not.toHaveBeenCalled();
  expect(dialog).toHaveTextContent(/only the pending suggestions/);
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Discard pending suggestions" }),
  );
  expect(state.discard).toHaveBeenCalledOnce();
  expect(started).toHaveBeenCalledOnce();
});
it("keeps a discard failure visible inside the dialog", async () => {
  state.discard.mockRejectedValue(new Error("Already applied"));
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Discard pending suggestions" }),
  );
  expect(await within(screen.getByRole("dialog")).findByRole("alert")).toBeInTheDocument();
});

it("keeps a failed estimate out of the discard dialog", async () => {
  state.estimate.mockRejectedValue(new Error("The improvement session stopped"));
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("The improvement session stopped");
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(within(screen.getByRole("dialog")).queryByRole("alert")).not.toBeInTheDocument();
});

it("makes improving again the primary action for a mixed result", () => {
  render(
    <ContinueSession
      session={{
        ...SESSION,
        iterations: SESSION.iterations.map((r) => ({
          ...r,
          verdict: "regression",
          verdict_detail: { fixed: 3, broken: 1 },
        })),
      }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toHaveClass("bg-primary");
});
it("still tries again after two rounds with no change, while attempts are left", () => {
  const first = { ...SESSION.iterations[0]!, verdict: "no_change" as const };
  const second = { ...first, id: "r2", number: 2 };
  render(
    <ContinueSession
      session={{
        ...SESSION,
        status: "stopped",
        stop_reason: "no_change",
        iteration: 2,
        iterations: [first, second],
      }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toBeEnabled();
});
it("tries again after an inconclusive check, and stops at the attempt limit", () => {
  const measured = { ...SESSION.iterations[0]!, verdict: "inconclusive" as const };
  const view = render(
    <ContinueSession
      session={{
        ...SESSION,
        status: "stopped",
        stop_reason: "inconclusive",
        iterations: [measured],
      }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toBeEnabled();
  view.rerender(
    <ContinueSession
      session={{
        ...SESSION,
        status: "stopped",
        stop_reason: "no_change",
        iteration: SESSION.max_iterations,
      }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
});
it("resumes a step stopped for lost access under whoever presses it", () => {
  render(
    <ContinueSession
      session={{ ...SESSION, status: "stopped", stop_reason: "permission", stage: "proposing" }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Continue this step with my access" })).toBeEnabled();
});
it.each(["no_data", "knowledge_only", "repeat_candidate", "stale"])(
  "does not bypass the %s stop reason",
  (stop_reason) => {
    render(
      <ContinueSession
        session={{ ...SESSION, status: "stopped", stop_reason }}
        onStarted={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
  },
);
it("does not invent an available next round when there is no measured candidate", () => {
  render(
    <ContinueSession
      session={{ ...SESSION, status: "stopped", iterations: [] }}
      onStarted={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: "Improve again" })).toBeDisabled();
});
it("invalidates a visible quote when a newer measurement arrives", async () => {
  const view = render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await screen.findByRole("button", { name: "Confirm the estimate and continue" });
  view.rerender(
    <ContinueSession
      session={{
        ...SESSION,
        spent_usd: "0.05",
        iterations: SESSION.iterations.map((r) => ({ ...r, eval_run_ids: ["new"] })),
      }}
      onStarted={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: "Confirm the estimate and continue" }),
  ).not.toBeInTheDocument();
});
it("keeps the wizard at the result when a confirmed continuation is refused", async () => {
  state.start.mockRejectedValue(new Error("Quote changed"));
  const started = vi.fn();
  render(<ContinueSession session={SESSION} onStarted={started} />);
  await userEvent.click(screen.getByRole("button", { name: "Improve again" }));
  await userEvent.click(screen.getByRole("button", { name: "Estimate continuing the session" }));
  await userEvent.click(
    await screen.findByRole("button", { name: "Confirm the estimate and continue" }),
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(started).not.toHaveBeenCalled();
});
it("lets the person cancel the discard dialog without changing proposals", async () => {
  render(<ContinueSession session={SESSION} onStarted={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(state.discard).not.toHaveBeenCalled();
});
