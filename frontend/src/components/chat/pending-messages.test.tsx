import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PendingMessages } from "./pending-messages";

describe("a queued question with page context", () => {
  it("shows the original page and prevents sending it as a text-only correction", () => {
    const onSendNow = vi.fn();
    render(
      <PendingMessages
        messages={[
          {
            id: "q-1",
            content: "Explain this order",
            submission: {
              agentId: "agent-1",
              pageContext: {
                path: "/tables/orders",
                title: "Orders",
                captured_at: "2026-01-01T00:00:00.000Z",
              },
            },
          },
        ]}
        onCancel={vi.fn()}
        onSendNow={onSendNow}
      />,
    );

    expect(screen.getByText("Page: Orders")).toBeInTheDocument();
    const sendNow = screen.getByRole("button", { name: "Send now" });
    expect(sendNow).toBeDisabled();
    fireEvent.click(sendNow);
    expect(onSendNow).not.toHaveBeenCalled();
  });

  it("also preserves a fixed agent when page sharing was off", () => {
    render(
      <PendingMessages
        messages={[
          {
            id: "q-1",
            content: "A general question",
            submission: { agentId: "agent-1", pageContext: null },
          },
        ]}
        onCancel={vi.fn()}
        onSendNow={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Send now" })).toBeDisabled();
    expect(screen.queryByText(/^Page:/)).not.toBeInTheDocument();
  });

  it("leaves ordinary text-only chat corrections available", () => {
    const onSendNow = vi.fn();
    render(
      <PendingMessages
        messages={[{ id: "q-1", content: "Use the latest figures" }]}
        onCancel={vi.fn()}
        onSendNow={onSendNow}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    expect(onSendNow).toHaveBeenCalledWith("q-1");
  });
});
