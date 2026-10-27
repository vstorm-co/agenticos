import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { SESSION } from "@/test-utils/improvement";
import type { ContinuationEstimate, Improvement } from "@/types/improvement";
import { NextStep } from "./next-step";
import { ReadOnlyProvider } from "./read-only";

const state = vi.hoisted(() => ({ estimate: vi.fn(), start: vi.fn(), pending: false }));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({
    estimateContinuation: { mutateAsync: state.estimate },
    continueSession: { mutateAsync: state.start, isPending: state.pending },
  }),
}));

const QUOTE: ContinuationEstimate = {
  mode: "next_step",
  number: 1,
  total_usd: "0.04",
  budget_usd: "1",
  affordable: true,
  candidate_hash: "a".repeat(64),
};
const AT_UNDERSTAND: Improvement = { ...SESSION, status: "waiting", stage: "classifying" };
const AT_CHANGES: Improvement = { ...SESSION, status: "waiting", stage: "filtering" };

beforeEach(() => {
  vi.clearAllMocks();
  state.pending = false;
  state.estimate.mockResolvedValue(QUOTE);
  state.start.mockResolvedValue(AT_UNDERSTAND);
});

it("prices the next step before anyone asks, and pressing it consents to that price", async () => {
  const started = vi.fn();
  render(<NextStep session={AT_UNDERSTAND} onStarted={started} />);
  expect(screen.getByRole("status")).toHaveTextContent("Pricing the next step…");
  expect(screen.getByRole("button", { name: "Next step: write the changes" })).toBeDisabled();
  const go = await screen.findByRole("button", {
    name: "Next step: write the changes · up to $0.04",
  });
  expect(state.estimate).toHaveBeenCalledWith(AT_UNDERSTAND.budget_usd);
  expect(state.start).not.toHaveBeenCalled();
  await userEvent.click(go);
  expect(state.start).toHaveBeenCalledWith(QUOTE);
  expect(started).toHaveBeenCalledOnce();
});

it("names testing the selected changes at the stop after Changes, and waits for a selection", async () => {
  const view = render(
    <NextStep session={AT_CHANGES} blocked="Select at least one change" onStarted={vi.fn()} />,
  );
  const go = await screen.findByRole("button", {
    name: "Next step: test the selected changes · up to $0.04",
  });
  expect(go).toBeDisabled();
  expect(screen.getByText("Select at least one change")).toBeInTheDocument();
  view.rerender(<NextStep session={AT_CHANGES} onStarted={vi.fn()} />);
  expect(go).toBeEnabled();
});

it("prices the check again once the changes it measures are chosen or reworded", async () => {
  const attempt = (hash: string): Improvement => ({
    ...AT_CHANGES,
    iterations: [{ ...SESSION.iterations[0]!, candidate_spec_hash: hash }],
  });
  const view = render(<NextStep session={attempt("a".repeat(64))} onStarted={vi.fn()} />);
  await screen.findByRole("button", { name: "Next step: test the selected changes · up to $0.04" });
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "0.05", candidate_hash: "b".repeat(64) });
  view.rerender(<NextStep session={attempt("b".repeat(64))} onStarted={vi.fn()} />);
  await userEvent.click(
    await screen.findByRole("button", {
      name: "Next step: test the selected changes · up to $0.05",
    }),
  );
  expect(state.estimate).toHaveBeenCalledTimes(2);
  expect(state.start).toHaveBeenCalledWith(
    expect.objectContaining({ candidate_hash: "b".repeat(64) }),
  );
});

it("re-prices after a changed price and says so before anything is spent", async () => {
  state.start.mockRejectedValueOnce(new ApiError(409, "The price changed"));
  render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  const first = await screen.findByRole("button", {
    name: "Next step: write the changes · up to $0.04",
  });
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "0.06" });
  await userEvent.click(first);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The price changed to up to $0.06. Press again to go on.",
  );
  const again = screen.getByRole("button", { name: "Next step: write the changes · up to $0.06" });
  state.start.mockResolvedValue(AT_UNDERSTAND);
  await userEvent.click(again);
  expect(state.start).toHaveBeenLastCalledWith({ ...QUOTE, total_usd: "0.06" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("says why the press failed, and why a changed price could not be read", async () => {
  state.start.mockRejectedValueOnce(new Error("AI assistance is off"));
  render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  await userEvent.click(
    await screen.findByRole("button", { name: "Next step: write the changes · up to $0.04" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("AI assistance is off");
  state.start.mockRejectedValueOnce(new ApiError(409, "The price changed"));
  state.estimate.mockRejectedValueOnce(new Error("Pricing is unavailable"));
  await userEvent.click(
    screen.getByRole("button", { name: "Next step: write the changes · up to $0.04" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Pricing is unavailable");
});

it("asks for a higher limit when the next step costs more than is left", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, affordable: false, total_usd: "2" });
  render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  expect(await screen.findByText(/costs more than this session has left/)).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Next step: write the changes · up to $2.00" }),
  ).toBeDisabled();
  const raise = screen.getByRole("button", { name: "Price it again" });
  expect(raise).toBeDisabled();
  await userEvent.clear(screen.getByLabelText(/limit/i));
  await userEvent.type(screen.getByLabelText(/limit/i), "3");
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "2", budget_usd: "3" });
  await userEvent.click(raise);
  expect(state.estimate).toHaveBeenLastCalledWith("3");
  expect(
    await screen.findByRole("button", { name: "Next step: write the changes · up to $2.00" }),
  ).toBeEnabled();
});

it("says a step that cannot be measured is final for this session, rather than asking for questions", async () => {
  state.estimate.mockRejectedValue(
    new ApiError(400, "Add 1 more test questions to measure this attempt", {
      error: { code: "BAD_REQUEST", message: "x", details: { missing_holdout: 1 } },
    }),
  );
  render(<NextStep session={AT_CHANGES} onStarted={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /can't be tested: 1 more question kept aside .* end the session, add questions, and start a new one\./,
  );
});

it("says why a price could not be read", async () => {
  state.estimate.mockRejectedValue(new Error("Pricing is unavailable"));
  render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Pricing is unavailable");
});

it("offers nothing on a session that is not stopped for a person, or that is only read", () => {
  const { container, rerender } = render(
    <NextStep
      session={{ ...SESSION, status: "running", stage: "proposing" }}
      onStarted={vi.fn()}
    />,
  );
  expect(container).toBeEmptyDOMElement();
  rerender(
    <ReadOnlyProvider value="viewOnly">
      <NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />
    </ReadOnlyProvider>,
  );
  expect(container).toBeEmptyDOMElement();
  expect(state.estimate).not.toHaveBeenCalled();
});

it("drops a price or a refusal that arrives after the footer is gone", async () => {
  let settle: (value: ContinuationEstimate) => void = () => {};
  state.estimate.mockReturnValueOnce(new Promise((resolve) => (settle = resolve)));
  const first = render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  first.unmount();
  settle(QUOTE);
  let refuse: (reason: Error) => void = () => {};
  state.estimate.mockReturnValueOnce(new Promise((_, reject) => (refuse = reject)));
  const second = render(<NextStep session={AT_UNDERSTAND} onStarted={vi.fn()} />);
  second.unmount();
  refuse(new Error("Pricing is unavailable"));
  await Promise.resolve();
  expect(state.start).not.toHaveBeenCalled();
});

it("offers nothing to a reader who may not start an improvement on the agent", () => {
  const { container } = render(
    <NextStep session={{ ...AT_UNDERSTAND, can_restart: false }} onStarted={vi.fn()} />,
  );
  expect(container).toBeEmptyDOMElement();
  expect(state.estimate).not.toHaveBeenCalled();
});

it("prices a check as the most it may cost, and says what it most likely costs", async () => {
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "0.28", expected_usd: "0.07" });
  const view = render(<NextStep session={AT_CHANGES} onStarted={vi.fn()} />);
  expect(
    await screen.findByRole("button", { name: /test the selected changes · up to \$0\.28/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByText(
      "Most likely about $0.07: the higher figure holds only if answers have to be asked again.",
    ),
  ).toBeInTheDocument();
  state.estimate.mockResolvedValue({ ...QUOTE, total_usd: "0.04", expected_usd: "0.04" });
  view.unmount();
  render(<NextStep session={AT_CHANGES} onStarted={vi.fn()} />);
  await screen.findByRole("button", { name: /up to \$0\.04/ });
  expect(screen.queryByText(/Most likely/)).not.toBeInTheDocument();
});
