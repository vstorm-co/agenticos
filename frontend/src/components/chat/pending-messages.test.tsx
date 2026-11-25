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

  it("keeps Send now and Run as task available for an accepted plain-text receipt", () => {
    const onSendNow = vi.fn();
    const onRunAsTask = vi.fn();
    render(
      <PendingMessages
        queueReceiptsEnabled
        steerAgentId="agent-1"
        messages={[
          {
            id: "q-1",
            clientQueueId: "123e4567-e89b-42d3-a456-426614174000",
            acceptedQueueId: "123e4567-e89b-42d3-a456-426614174001",
            receiptState: "pending",
            content: "Use the latest figures",
            agentId: "agent-1",
            submission: {
              agentId: "agent-1",
              pageContext: null,
              local: { payload: null, fileRoot: null, projectId: null },
            },
          },
        ]}
        onCancel={vi.fn()}
        onSendNow={onSendNow}
        onRunAsTask={onRunAsTask}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Send now" }));
    fireEvent.click(screen.getByRole("button", { name: "Run as task" }));
    expect(onSendNow).toHaveBeenCalledWith("q-1");
    expect(onRunAsTask).toHaveBeenCalledWith("q-1");
  });

  it("disables Send now when the live run uses another agent", () => {
    render(
      <PendingMessages
        queueReceiptsEnabled
        steerAgentId="agent-2"
        messages={[
          {
            id: "q-1",
            acceptedQueueId: "123e4567-e89b-42d3-a456-426614174001",
            receiptState: "pending",
            content: "Use the reviewed figures",
            agentId: "agent-1",
          },
        ]}
        onCancel={vi.fn()}
        onSendNow={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Send now" })).toBeDisabled();
    expect(
      screen.getByTitle(
        "Send now is available when this chat is running the queued message's agent",
      ),
    ).toBeInTheDocument();
  });

  it("uses restored file IDs to block text-only steering", () => {
    render(
      <PendingMessages
        queueReceiptsEnabled
        messages={[
          {
            id: "q-1",
            acceptedQueueId: "123e4567-e89b-42d3-a456-426614174001",
            receiptState: "pending",
            content: "Read the file",
            fileIds: ["file-1"],
          },
        ]}
        onCancel={vi.fn()}
        onSendNow={vi.fn()}
      />,
    );

    expect(screen.getByText("1 file")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send now" })).toBeDisabled();
  });

  it("explains when a local grant cannot move to a task", () => {
    render(
      <PendingMessages
        queueReceiptsEnabled
        messages={[
          {
            id: "q-1",
            acceptedQueueId: "123e4567-e89b-42d3-a456-426614174001",
            receiptState: "pending",
            content: "Use my computer",
            submission: {
              agentId: "agent-1",
              pageContext: null,
              local: {
                payload: { computer_grant: "grant-1" },
                fileRoot: null,
                projectId: null,
              },
            },
          },
        ]}
        onCancel={vi.fn()}
        onRunAsTask={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Whole-computer access cannot be transferred to a task yet"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run as task" })).toBeDisabled();
  });
});
