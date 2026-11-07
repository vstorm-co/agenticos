import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { qk } from "@/lib/query-keys";
import * as api from "@/lib/workflows/runs-api";
import type { WorkflowQuestionRead, WorkflowRunRead } from "@/lib/workflows/types";

import { useWorkflowChatRun, useWorkflowRunQuestions } from "./use-workflow-questions";

vi.mock("@/lib/workflows/runs-api", () => ({
  getWorkflowRun: vi.fn(),
  listWorkflowRunQuestions: vi.fn(),
  answerWorkflowRunQuestions: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const entry: WorkflowQuestionRead = {
  workflow_run_id: "run",
  node_run_id: "node",
  agent_run_id: "agent-run",
  questions: [
    { tool_call_id: "tool", questions: [{ question: "Which scope?", allow_custom: true }] },
  ],
};
const run = (status: WorkflowRunRead["status"]) =>
  ({ id: "run", workflow_id: "wf", status }) as WorkflowRunRead;

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.useRealTimers());

describe("workflow questions", () => {
  it("reads only server-authorized questions and refreshes the existing run after answering", async () => {
    vi.mocked(api.listWorkflowRunQuestions).mockResolvedValueOnce([entry]).mockResolvedValue([]);
    vi.mocked(api.answerWorkflowRunQuestions).mockResolvedValue(run("running"));
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    expect(result.current.questions).toEqual([]);
    await waitFor(() => expect(result.current.questions).toEqual([entry]));
    client.setQueryData(qk.workflows.run("run"), run("waiting_for_user"));
    const responses = { tool: [{ answer: "This quarter", skipped: false }] };
    await act(() =>
      result.current.answer.mutateAsync({ workflowRunId: "run", nodeRunId: "node", responses }),
    );
    expect(api.answerWorkflowRunQuestions).toHaveBeenCalledWith("run", "node", responses);
    expect(client.getQueryData(qk.workflows.run("run"))).toEqual(run("running"));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.run("run") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.runs("wf") });
  });

  it("keeps another branch's unanswered questions while accepted answers resume their step", async () => {
    const other = { ...entry, node_run_id: "other" };
    vi.mocked(api.listWorkflowRunQuestions)
      .mockResolvedValueOnce([entry, other])
      .mockResolvedValue([other]);
    vi.mocked(api.answerWorkflowRunQuestions).mockResolvedValue(run("waiting_for_user"));
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await waitFor(() => expect(result.current.questions).toHaveLength(2));
    await act(() =>
      result.current.answer.mutateAsync({
        workflowRunId: "run",
        nodeRunId: "node",
        responses: { tool: [{ answer: "This quarter", skipped: false }] },
      }),
    );
    await waitFor(() =>
      expect(client.getQueryData(qk.workflows.runQuestions("run"))).toEqual([other]),
    );
  });

  it("reports a failed answer and rereads state after a duplicate, expiry or cancellation", async () => {
    vi.mocked(api.listWorkflowRunQuestions).mockResolvedValue([]);
    vi.mocked(api.answerWorkflowRunQuestions).mockRejectedValue(new Error("Question expired"));
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await act(async () => {
      await result.current.answer
        .mutateAsync({ workflowRunId: "run", nodeRunId: "node", responses: {} })
        .catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.run("run") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.runQuestions("run") });
  });

  it("preserves later questions and a terminal run when an older answer response arrives", async () => {
    const submitted = Promise.withResolvers<WorkflowRunRead>();
    const reread = Promise.withResolvers<WorkflowQuestionRead[]>();
    vi.mocked(api.listWorkflowRunQuestions)
      .mockResolvedValueOnce([entry])
      .mockReturnValue(reread.promise);
    vi.mocked(api.answerWorkflowRunQuestions).mockReturnValue(submitted.promise);
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await waitFor(() => expect(result.current.questions).toEqual([entry]));
    act(() =>
      result.current.answer.mutate({
        workflowRunId: "run",
        nodeRunId: "node",
        responses: { tool: [{ answer: "Quarter", skipped: false }] },
      }),
    );
    await waitFor(() => expect(api.answerWorkflowRunQuestions).toHaveBeenCalledTimes(1));
    const later = { ...entry, questions: [{ ...entry.questions[0]!, tool_call_id: "next" }] };
    const parallel = { ...entry, node_run_id: "new-parallel-step" };
    act(() => {
      client.setQueryData(qk.workflows.runQuestions("run"), [later, parallel]);
      client.setQueryData(qk.workflows.run("run"), run("succeeded"));
    });
    await act(async () => submitted.resolve(run("waiting_for_user")));
    await waitFor(() => expect(result.current.answer.isSuccess).toBe(true));
    expect(client.getQueryData(qk.workflows.runQuestions("run"))).toEqual([later, parallel]);
    expect(client.getQueryData(qk.workflows.run("run"))).toEqual(run("succeeded"));
    await act(async () => reread.resolve([later, parallel]));
  });

  it("does not restore another branch's questions after the view clears its cache", async () => {
    const submitted = Promise.withResolvers<WorkflowRunRead>();
    const parallel = { ...entry, node_run_id: "other-private-step" };
    vi.mocked(api.listWorkflowRunQuestions).mockResolvedValue([entry, parallel]);
    vi.mocked(api.answerWorkflowRunQuestions).mockReturnValue(submitted.promise);
    const { client, wrapper } = setup();
    const { result, unmount } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await waitFor(() => expect(result.current.questions).toEqual([entry, parallel]));
    act(() =>
      result.current.answer.mutate({
        workflowRunId: "run",
        nodeRunId: "node",
        responses: { tool: [{ answer: "Quarter", skipped: false }] },
      }),
    );
    await waitFor(() => expect(api.answerWorkflowRunQuestions).toHaveBeenCalledTimes(1));
    unmount();
    client.removeQueries({ queryKey: qk.workflows.runQuestions("run"), exact: true });
    await act(async () => submitted.resolve(run("running")));
    await waitFor(() =>
      expect(client.getQueryData(qk.workflows.run("run"))).toEqual(run("running")),
    );
    expect(client.getQueryData(qk.workflows.runQuestions("run"))).toBeUndefined();
  });

  it("refreshes both the originating view and the actual child after a failed nested answer", async () => {
    vi.mocked(api.listWorkflowRunQuestions).mockResolvedValue([]);
    vi.mocked(api.answerWorkflowRunQuestions).mockRejectedValue(new Error("Question expired"));
    const { client, wrapper } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await act(async () => {
      await result.current.answer
        .mutateAsync({
          workflowRunId: "child",
          nodeRunId: "node",
          responses: {},
        })
        .catch(() => undefined);
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.run("child") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.runQuestions("run") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.run("run") });
  });

  it("exposes question read failures and can retry", async () => {
    vi.mocked(api.listWorkflowRunQuestions)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue([]);
    const { wrapper } = setup();
    const { result } = renderHook(() => useWorkflowRunQuestions("run"), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    await act(() => result.current.refetch());
    await waitFor(() => expect(result.current.error).toBeNull());
  });
});

it("follows a reloaded chat run through a saved question and stops polling once it ends", async () => {
  vi.mocked(api.getWorkflowRun)
    .mockResolvedValueOnce(run("waiting_for_user"))
    .mockResolvedValue(run("succeeded"));
  const { wrapper } = setup();
  const { result } = renderHook(() => useWorkflowChatRun("run"), { wrapper });
  await waitFor(() => expect(result.current.data?.status).toBe("waiting_for_user"));
  await waitFor(() => expect(result.current.data?.status).toBe("succeeded"));
  await act(() => new Promise((resolve) => setTimeout(resolve, 2200)));
  expect(api.getWorkflowRun).toHaveBeenCalledTimes(2);
});
