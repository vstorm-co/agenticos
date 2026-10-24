import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { hunk } from "@/test-utils/authoring";
import { SESSION } from "@/test-utils/improvement";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { ChangeSelection } from "./change-selection";
const actions = vi.hoisted(() => ({
  estimateSelection: { mutateAsync: vi.fn(), isPending: false },
  checkSelection: { mutateAsync: vi.fn(), isPending: false },
  started: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({ useImprovement: () => actions }));
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
