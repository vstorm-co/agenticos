import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReplyExpectation } from "@/lib/workflows/types";
import { ReplyExpectationControl } from "./reply-expectation-control";

const save = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-workflow-runs", () => ({
  useEditReplyExpectation: () => ({ mutate: save, isPending: false }),
}));
const value: ReplyExpectation = {
  provider: "google",
  connection_id: "account",
  authorization_generation: "consent",
  thread_id: "thread",
  expected_sender: "alice@example.com",
  not_before: "2026-11-03T10:00:00Z",
  deadline: "2026-11-04T10:00:00Z",
  anchor_message_id: null,
  paused: false,
};

beforeEach(() => {
  save.mockReset();
});
describe("reply expectation controls", () => {
  it("shows state but hides controls without resolution authority", () => {
    render(<ReplyExpectationControl runId="r" nodeRunId="n" value={value} editable={false} />);
    expect(screen.getByText(/Waiting for alice@example.com/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Edit reply expectation" }),
    ).not.toBeInTheDocument();
  });
  it("saves corrected sender and pause without implicitly accepting renewed consent", () => {
    render(<ReplyExpectationControl runId="r" nodeRunId="n" value={value} editable />);
    fireEvent.click(screen.getByRole("button", { name: "Edit reply expectation" }));
    fireEvent.change(screen.getByLabelText("Expected sender"), {
      target: { value: "bob@example.com" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Pause checks; keep the deadline" }));
    fireEvent.click(screen.getByRole("button", { name: "Save expectation" }));
    expect(save).toHaveBeenCalledWith(
      {
        thread_id: "thread",
        expected_sender: "bob@example.com",
        not_before: value.not_before,
        deadline: value.deadline,
        anchor_message_id: null,
        paused: true,
        review_mailbox: false,
      },
      expect.any(Object),
    );
    expect(screen.queryByLabelText(/Connection ID/)).not.toBeInTheDocument();
  });
  it("allows an explicit review of the same account", () => {
    render(
      <ReplyExpectationControl
        runId="r"
        nodeRunId="n"
        value={{ ...value, paused: true }}
        editable
      />,
    );
    expect(screen.getByText(/Paused reply expectation/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit reply expectation" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Accept renewed consent on this same mailbox" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save expectation" }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({ review_mailbox: true, paused: true }),
      expect.any(Object),
    );
  });
});

it("closes after a successful expectation update", () => {
  save.mockImplementation((_value: unknown, options: { onSuccess: () => void }) =>
    options.onSuccess(),
  );
  render(<ReplyExpectationControl runId="r" nodeRunId="n" value={value} editable />);
  fireEvent.click(screen.getByRole("button", { name: "Edit reply expectation" }));
  fireEvent.click(screen.getByRole("button", { name: "Save expectation" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
