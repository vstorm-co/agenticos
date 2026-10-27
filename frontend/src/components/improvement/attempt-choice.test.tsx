import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement, ImprovementIteration } from "@/types/improvement";
import { AttemptChoice } from "./attempt-choice";
import { ReadOnlyProvider } from "./read-only";

const state = vi.hoisted(() => ({
  selectRound: { mutateAsync: vi.fn(), isPending: false },
}));
vi.mock("@/hooks/use-improvements", () => ({ useImprovement: () => state }));

const BASE = SESSION.iterations[0]!;
const round = (
  number: number,
  verdict: ImprovementIteration["verdict"],
  { fixed = 0, broken = 0 } = {},
): ImprovementIteration => ({
  ...BASE,
  id: `r${number}`,
  number,
  verdict,
  verdict_detail: { fixed, broken, held_out: 10 },
});
/** Two measured attempts: the first better and kept, the second mixed. */
const TWO: Improvement = {
  ...SESSION,
  status: "ready",
  best_iteration_id: "r1",
  iterations: [round(1, "better", { fixed: 3 }), round(2, "regression", { fixed: 4, broken: 2 })],
};

const show = (session: Improvement) =>
  render(<AttemptChoice session={session} agent="Refund desk" />);
const option = (number: number) => screen.getByRole("radio", { name: `Keep attempt ${number}` });

beforeEach(() => {
  vi.clearAllMocks();
  state.selectRound.isPending = false;
  state.selectRound.mutateAsync.mockResolvedValue(TWO);
});

it("offers no choice when only one attempt was measured", () => {
  const { container } = show({ ...TWO, iterations: [TWO.iterations[0]!] });
  expect(container).toBeEmptyDOMElement();
});

it("lists every measured attempt with the kept one ticked and nothing to press", () => {
  show(TWO);
  expect(screen.getByRole("group", { name: "Which attempt to keep" })).toBeInTheDocument();
  expect(option(1)).toBeChecked();
  expect(option(2)).not.toBeChecked();
  expect(screen.getByText("Best attempt")).toBeInTheDocument();
  expect(screen.getByText("+3 fixed · 0 broken of 10 kept aside")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("warns before keeping an attempt that broke questions, and keeps it on confirmation", async () => {
  show(TWO);
  await userEvent.click(option(2));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Attempt 2 broke 2 questions. Accepting it will make Refund desk worse on those.",
  );
  expect(state.selectRound.mutateAsync).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Keep attempt 2 anyway" }));
  expect(state.selectRound.mutateAsync).toHaveBeenCalledWith(2);
});

it("says an attempt that changed nothing brings no measured gain", async () => {
  show({ ...TWO, iterations: [TWO.iterations[0]!, round(2, "no_change")] });
  await userEvent.click(option(2));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Attempt 2 did not make Refund desk better. Accepting it changes Refund desk with no measured gain.",
  );
});

it("keeps a better attempt without a warning, and drops the button once it is kept", async () => {
  const session = {
    ...TWO,
    best_iteration_id: "r2",
    iterations: [round(1, "no_change"), round(2, "better", { fixed: 2 })],
  };
  const view = show(session);
  await userEvent.click(option(1));
  await userEvent.click(option(2));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  await userEvent.click(option(1));
  await userEvent.click(screen.getByRole("button", { name: "Keep attempt 1 anyway" }));
  view.rerender(
    <AttemptChoice session={{ ...session, best_iteration_id: "r1" }} agent="Refund desk" />,
  );
  expect(option(1)).toBeChecked();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("asks a stopped session to keep its preselected attempt, which nothing has kept yet", async () => {
  show({ ...TWO, status: "stopped", best_iteration_id: "r1" });
  expect(option(1)).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Keep attempt 1" }));
  expect(state.selectRound.mutateAsync).toHaveBeenCalledWith(1);
});

it("waits for a choice when a stopped session has none", () => {
  show({ ...TWO, status: "stopped", best_iteration_id: null });
  expect(option(1)).not.toBeChecked();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("reports a refused choice", async () => {
  state.selectRound.mutateAsync.mockRejectedValue(new Error("The base changed"));
  show(TWO);
  await userEvent.click(option(2));
  await userEvent.click(screen.getByRole("button", { name: "Keep attempt 2 anyway" }));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
});

it.each([
  ["a decided session", { ...TWO, status: "published" as const }, null],
  ["a wizard only read", TWO, "finished" as const],
])("shows %s's chosen attempt with nothing to change", (_, session, readOnly) => {
  render(
    <ReadOnlyProvider value={readOnly}>
      <AttemptChoice session={session} agent="Refund desk" />
    </ReadOnlyProvider>,
  );
  expect(screen.getByRole("heading", { name: "Which attempt to keep" })).toBeInTheDocument();
  expect(screen.getByText("Best attempt")).toBeInTheDocument();
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
