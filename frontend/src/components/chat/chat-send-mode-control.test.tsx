import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatSendModeControl } from "./chat-send-mode-control";

describe("ChatSendModeControl", () => {
  it("is a native radio choice and selects Queue by default", () => {
    const onChange = vi.fn();
    const view = render(<ChatSendModeControl value="queue" onChange={onChange} />);

    expect(screen.getByRole("group", { name: "Send while running" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Queue" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Steer" })).toBeEnabled();

    fireEvent.click(screen.getByRole("radio", { name: "Steer" }));
    expect(onChange).toHaveBeenCalledWith("steer");

    view.rerender(<ChatSendModeControl value="steer" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Queue" }));
    expect(onChange).toHaveBeenLastCalledWith("queue");
  });

  it("describes direct steering while it is available", () => {
    render(<ChatSendModeControl value="steer" onChange={vi.fn()} />);

    expect(screen.getByText("Send guidance into the current turn.")).toBeInTheDocument();
  });

  it("explains why steering is disabled when the message has context", () => {
    render(<ChatSendModeControl value="steer" onChange={vi.fn()} unavailableReason="context" />);

    expect(screen.getByRole("radio", { name: "Steer" })).toBeDisabled();
    expect(
      screen.getByText(
        "Steering supports plain text. Messages with files, mentions, replies, page context, or workflow inputs stay queued.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the selected mode visible while disconnected", () => {
    render(
      <ChatSendModeControl value="steer" onChange={vi.fn()} unavailableReason="disconnected" />,
    );

    expect(screen.getByRole("radio", { name: "Steer" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Steer" })).toBeDisabled();
    expect(
      screen.getByText("Reconnect to steer the current turn. Your draft is still in the composer."),
    ).toBeVisible();
  });
});
