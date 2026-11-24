import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { MessageJumpNotice } from "./message-jump-notice";

it("keeps successful and absent jumps out of the conversation", () => {
  const jump = { status: "idle" as const, retry: vi.fn(), cancel: vi.fn() };
  const view = render(<MessageJumpNotice jump={jump} />);
  expect(view.container).toBeEmptyDOMElement();
  view.rerender(<MessageJumpNotice jump={{ ...jump, status: "found" }} />);
  expect(view.container).toBeEmptyDOMElement();
});

it("announces loading and allows cancellation", async () => {
  const jump = { status: "loading" as const, retry: vi.fn(), cancel: vi.fn() };
  render(<MessageJumpNotice jump={jump} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading the selected message");
  await userEvent.click(screen.getByRole("button", { name: "Cancel jump" }));
  expect(jump.cancel).toHaveBeenCalledOnce();
  expect(jump.retry).not.toHaveBeenCalled();
});

it("offers retry for failed reads and only dismissal for unavailable messages", async () => {
  const jump = { status: "failed" as const, retry: vi.fn(), cancel: vi.fn() };
  const view = render(<MessageJumpNotice jump={jump} />);
  expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(jump.retry).toHaveBeenCalledOnce();
  view.rerender(<MessageJumpNotice jump={{ ...jump, status: "unavailable" }} />);
  expect(screen.getByRole("alert")).toHaveTextContent("no longer available");
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(jump.cancel).toHaveBeenCalledOnce();
});
