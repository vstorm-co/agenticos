import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { WorkflowQuestionRead } from "@/lib/workflows/types";

import { WorkflowRunCard } from "./workflow-run-card";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const question: WorkflowQuestionRead = {
  workflow_run_id: "run",
  node_run_id: "step",
  agent_run_id: "agent-run",
  questions: [
    {
      tool_call_id: "clarify",
      questions: [
        {
          question: "What should the plan cover?",
          options: [{ label: "Onboarding" }],
          allow_custom: true,
        },
      ],
    },
  ],
};

beforeEach(() => vi.clearAllMocks());

describe("a reloaded workflow chat card", () => {
  it("shows the saved failure reason when polling discovers the run has ended", async () => {
    vi.mocked(apiClient.get).mockImplementation((url) =>
      Promise.resolve(
        url.endsWith("/questions")
          ? []
          : {
              id: "run",
              workflow_id: "wf",
              status: "failed",
              error: { message: "The question expired before it was answered" },
            },
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <WorkflowRunCard
          run={{
            runId: "run",
            workflowId: "wf",
            workflowName: "Planner",
            status: "running",
            error: null,
          }}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("The question expired before it was answered")).toBeInTheDocument();
  });

  it("restores the waiting question and sends the answer to the same workflow step", async () => {
    let answered = false;
    vi.mocked(apiClient.get).mockImplementation((url) =>
      Promise.resolve(
        url.endsWith("/questions")
          ? answered
            ? []
            : [question]
          : { id: "run", workflow_id: "wf", status: answered ? "running" : "waiting_for_user" },
      ),
    );
    vi.mocked(apiClient.post).mockImplementation(() => {
      answered = true;
      return Promise.resolve({ id: "run", workflow_id: "wf", status: "running" });
    });
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <WorkflowRunCard
          run={{
            runId: "run",
            workflowId: "wf",
            workflowName: "Planner",
            status: "running",
            error: null,
          }}
        />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Waiting for user")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Onboarding/ }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-runs/run/nodes/step/answers", {
        responses: { clarify: [{ answer: "", selected: ["Onboarding"], skipped: false }] },
      }),
    );
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.queryByText("What should the plan cover?")).toBeNull();

    // A later question starts a fresh prompt, and completion leaves answer delivery
    // to the chat transport rather than rendering a duplicate inside this card.
    act(() =>
      client.setQueryData(qk.workflows.runQuestions("run"), [
        {
          ...question,
          questions: [
            {
              ...question.questions[0],
              tool_call_id: "next",
              questions: [{ question: "Any constraints?", allow_custom: true }],
            },
          ],
        },
      ]),
    );
    expect(await screen.findByText("Any constraints?")).toBeInTheDocument();
    act(() =>
      client.setQueryData(qk.workflows.run("run"), {
        id: "run",
        status: "succeeded",
        output: { text: "The completed plan" },
      }),
    );
    expect(await screen.findByText("Succeeded")).toBeInTheDocument();
    expect(screen.queryByText("Any constraints?")).toBeNull();
    expect(screen.queryByText("The completed plan")).toBeNull();
  });
});
