import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ChatCompactionStatus } from "@/types/chat";
import { ChatCompactionControl, ChatCompactionNotice } from "./chat-compaction-control";

it("offers the supported action without submitting a chat message", async () => {
  const compact = vi.fn(() => true);
  const view = render(
    <ChatCompactionControl available={false} status="idle" onCompact={compact} />,
  );
  expect(view.container).toBeEmptyDOMElement();
  view.rerender(<ChatCompactionControl available status="idle" onCompact={compact} />);
  const button = screen.getByRole("button", { name: "Compact now" });
  expect(button).toHaveAttribute("type", "button");
  expect(button).toHaveAttribute("title", expect.stringContaining("Saved messages remain"));
  await userEvent.click(button);
  expect(compact).toHaveBeenCalledOnce();
});

it("blocks duplicate and busy requests while keeping progress visible", async () => {
  const compact = vi.fn(() => false);
  const view = render(
    <ChatCompactionControl available status="idle" disabled onCompact={compact} />,
  );
  const button = screen.getByRole("button", { name: "Compact now" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("title", "Available when this conversation is idle.");
  await userEvent.click(button);
  expect(compact).not.toHaveBeenCalled();
  view.rerender(<ChatCompactionControl available={false} status="running" onCompact={compact} />);
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
  view.rerender(<ChatCompactionControl available status="failed" onCompact={compact} />);
  expect(button).toBeEnabled();
  await userEvent.click(button);
  expect(compact).toHaveBeenCalledOnce();
});

it("announces progress with or without a message count", () => {
  const view = render(<ChatCompactionNotice status="idle" />);
  expect(view.container).toBeEmptyDOMElement();
  view.rerender(<ChatCompactionNotice status="running" />);
  expect(screen.getByRole("status")).toHaveTextContent("Summarizing earlier context");
  view.rerender(<ChatCompactionNotice status="running" messagesBefore={null} />);
  expect(screen.getByRole("status")).toHaveTextContent("Summarizing earlier context");
  view.rerender(<ChatCompactionNotice status="running" messagesBefore={12} />);
  expect(screen.getByRole("status")).toHaveTextContent("Summarizing 12 earlier messages");
});

it.each([
  ["compacted", "status", "Context compacted"],
  ["unchanged", "status", "No additional context"],
  ["busy", "alert", "This conversation is busy"],
  ["unavailable", "alert", "This agent cannot compact"],
  ["failed", "alert", "could not be compacted"],
] as const)(
  "reports %s without adding a transcript turn",
  (status: ChatCompactionStatus, role, text) => {
    render(<ChatCompactionNotice status={status} messagesBefore={12} />);
    expect(screen.getByRole(role)).toHaveTextContent(text);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  },
);
