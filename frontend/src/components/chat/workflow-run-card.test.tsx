import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";

import { TurnParts } from "./turn-parts";
import { WorkflowRunCard } from "./workflow-run-card";

describe("WorkflowRunCard", () => {
  it("names the workflow, says how its run ended and links to its steps", () => {
    render(
      <WorkflowRunCard
        run={{
          workflowId: "wf",
          workflowName: "Lead triage",
          runId: "r1",
          status: "failed",
          error: "The scoring step failed",
        }}
      />,
    );
    expect(screen.getByText("Lead triage")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByText("The scoring step failed")).toBeTruthy();
    expect(screen.getByRole("link", { name: "View its steps" }).getAttribute("href")).toBe(
      "/workflows/wf/runs/r1",
    );
  });

  it("has no link before the run is admitted, and a name when the workflow lost its own", () => {
    render(
      <WorkflowRunCard
        run={{ workflowId: "wf", workflowName: null, runId: null, status: "queued", error: null }}
      />,
    );
    expect(screen.getByText("Workflow")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("a workflow's turn read back from the conversation", () => {
  it("replays the card and then the words, in the order they were stored", async () => {
    const message = conversationMessageToChatMessage({
      id: "m1",
      conversation_id: "c1",
      role: "assistant",
      content: "Three are hot.",
      created_at: "2026-09-29T10:00:00Z",
      parts: [
        {
          type: "workflow_run",
          run_id: "r1",
          workflow_id: "wf",
          workflow_name: "Lead triage",
          status: "succeeded",
        },
        { type: "text", text: "Three are hot." },
      ],
    });
    expect(message.parts?.[0]).toMatchObject({
      type: "workflow_run",
      workflowRun: {
        workflowId: "wf",
        workflowName: "Lead triage",
        runId: "r1",
        status: "succeeded",
        error: null,
      },
    });

    render(
      <TurnParts parts={message.parts ?? []} isStreaming={false} isUser={false} mcpServers={[]} />,
    );
    expect(screen.getByText("Lead triage")).toBeTruthy();
    // Markdown renders lazily, so the words arrive a tick after the card.
    expect(await screen.findByText(/Three are hot/)).toBeTruthy();
  });

  it("reads a sparse stored entry as a finished run with no name", () => {
    const message = conversationMessageToChatMessage({
      id: "m2",
      conversation_id: "c1",
      role: "assistant",
      content: "",
      created_at: "2026-09-29T10:00:00Z",
      parts: [{ type: "workflow_run" }],
    });
    expect(message.parts?.[0]?.workflowRun).toEqual({
      workflowId: "",
      workflowName: null,
      runId: null,
      status: "succeeded",
      error: null,
    });
  });
});
