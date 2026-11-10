import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { WorkflowQuestionRead } from "@/lib/workflows/types";

import { WorkflowRunQuestions } from "./run-questions";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const entry: WorkflowQuestionRead = {
  workflow_run_id: "run",
  node_run_id: "step",
  agent_run_id: "same-agent-run",
  questions: [
    {
      tool_call_id: "scope",
      questions: [
        { question: "Which scope?", allow_custom: false, options: [{ label: "Quarter" }] },
      ],
    },
    {
      tool_call_id: "format",
      questions: [
        { question: "Which format?", allow_custom: false, options: [{ label: "Brief" }] },
      ],
    },
  ],
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkflowRunQuestions runId="run" />
    </QueryClientProvider>,
  );
  return client;
}

beforeEach(() => vi.clearAllMocks());

describe("answering a suspended workflow agent", () => {
  it("collects parallel tool calls and resumes their existing step with the corresponding answers", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([entry]).mockResolvedValue([]);
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "run",
      workflow_id: "wf",
      status: "running",
    });
    const user = userEvent.setup();
    const client = mount();
    expect(await screen.findByText("Which scope?")).toBeInTheDocument();
    expect(screen.getByText("Your agent needs an answer to continue")).toHaveAttribute(
      "data-tour",
      "workflow-run-questions",
    );
    await user.click(screen.getByRole("button", { name: /Quarter/ }));
    await user.click(screen.getByRole("button", { name: /Brief/ }));
    await user.click(screen.getByRole("button", { name: "Send answers" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-runs/run/nodes/step/answers", {
        responses: {
          scope: [{ answer: "", selected: ["Quarter"], skipped: false }],
          format: [{ answer: "", selected: ["Brief"], skipped: false }],
        },
      }),
    );
    expect(client.getQueryData(qk.workflows.run("run"))).toMatchObject({
      id: "run",
      status: "running",
    });
  });

  it("routes a nested workflow question to its child without replacing the displayed parent", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce([
        {
          ...entry,
          workflow_run_id: "child",
          questions: entry.questions.slice(0, 1),
        },
      ])
      .mockResolvedValue([]);
    const child = { id: "child", workflow_id: "child-workflow", status: "running" };
    vi.mocked(apiClient.post).mockResolvedValue(child);
    const user = userEvent.setup();
    const client = mount();
    const parent = { id: "run", workflow_id: "parent-workflow", status: "waiting_for_user" };
    client.setQueryData(qk.workflows.run("run"), parent);
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await user.click(await screen.findByRole("button", { name: /Quarter/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-runs/child/nodes/step/answers", {
        responses: { scope: [{ answer: "", selected: ["Quarter"], skipped: false }] },
      }),
    );
    await waitFor(() => expect(client.getQueryData(qk.workflows.run("child"))).toEqual(child));
    expect(client.getQueryData(qk.workflows.run("run"))).toEqual(parent);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.run("run") });
  });

  it("renders no controls for a viewer the server has not authorized to answer", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([]);
    mount();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/workflow-runs/run/questions"));
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("Which scope?")).toBeNull();
  });

  it("shows a failed question read and retries instead of silently rendering an empty state", async () => {
    vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([entry]);
    const user = userEvent.setup();
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The questions could not be loaded.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Which scope?")).toBeInTheDocument();
  });

  it("disables answering while an answer is being saved", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([
      { ...entry, questions: entry.questions.slice(0, 1) },
    ]);
    vi.mocked(apiClient.post).mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /Quarter/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Skip" })).toBeDisabled());
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
});
