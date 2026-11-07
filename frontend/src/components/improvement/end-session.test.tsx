import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { Improvement } from "@/types/improvement";
import { EndSession } from "./end-session";

const state = vi.hoisted(() => ({ cancel: vi.fn() }));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({ cancel: { mutateAsync: state.cancel, isPending: false } }),
}));

const WAITING: Improvement = { ...SESSION, status: "waiting", stage: "filtering" };

beforeEach(() => {
  vi.clearAllMocks();
  state.cancel.mockResolvedValue({});
});

it("ends a waiting session once the person confirms, keeping it in the history", async () => {
  render(<EndSession session={WAITING} />);
  await userEvent.click(screen.getByRole("button", { name: "End the session" }));
  expect(screen.getByText(/stays in the agent's history/)).toBeInTheDocument();
  expect(state.cancel).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "End it" }));
  expect(state.cancel).toHaveBeenCalledOnce();
});

it("says why the session could not be ended, and is not offered to whoever may not end it", async () => {
  state.cancel.mockRejectedValueOnce(new Error("Only the creator can stop this session"));
  const view = render(<EndSession session={WAITING} />);
  await userEvent.click(screen.getByRole("button", { name: "End the session" }));
  await userEvent.click(screen.getByRole("button", { name: "End it" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Only the creator can stop this session",
  );
  view.rerender(<EndSession session={{ ...WAITING, can_discard: false }} />);
  expect(screen.queryByRole("button", { name: "End the session" })).not.toBeInTheDocument();
});
