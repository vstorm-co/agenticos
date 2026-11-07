"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  answerWorkflowRunQuestions,
  getWorkflowRun,
  listWorkflowRunQuestions,
} from "@/lib/workflows/runs-api";
import {
  isRunTerminal,
  type WorkflowQuestionRead,
  type WorkflowQuestionResponses,
  type WorkflowRunRead,
} from "@/lib/workflows/types";

const LIVE_POLL_MS = 2000;

/** Read a chat card's saved run after reload, and follow it through later questions. */
export function useWorkflowChatRun(runId: string) {
  return useQuery({
    queryKey: qk.workflows.run(runId),
    queryFn: () => getWorkflowRun(runId),
    refetchInterval: (query) =>
      query.state.data !== undefined && isRunTerminal(query.state.data.status)
        ? false
        : LIVE_POLL_MS,
    retry: false,
  });
}

/** Server-filtered questions are the authority for who may see and answer them. */
export function useWorkflowRunQuestions(runId: string) {
  const client = useQueryClient();
  const tErrors = useTranslations("errors");
  const query = useQuery({
    queryKey: qk.workflows.runQuestions(runId),
    queryFn: () => listWorkflowRunQuestions(runId),
    refetchInterval: LIVE_POLL_MS,
    retry: false,
  });
  const questions = query.data ?? [];
  const refresh = () => {
    void client.invalidateQueries({ queryKey: qk.workflows.run(runId) });
    void client.invalidateQueries({ queryKey: qk.workflows.runQuestions(runId) });
  };
  const answer = useMutation({
    mutationFn: ({
      workflowRunId,
      nodeRunId,
      responses,
    }: {
      workflowRunId: string;
      nodeRunId: string;
      responses: WorkflowQuestionResponses;
    }) => answerWorkflowRunQuestions(workflowRunId, nodeRunId, responses),
    onSuccess: (run, { nodeRunId, responses }) => {
      // Polling can discover a later question before this response arrives.
      // Remove only the answered batch from the current cache.
      client.setQueryData<WorkflowQuestionRead[]>(qk.workflows.runQuestions(runId), (current) =>
        current?.filter(
          (entry) =>
            entry.node_run_id !== nodeRunId ||
            entry.questions.some((call) => !Object.hasOwn(responses, call.tool_call_id)),
        ),
      );
      // A nested workflow answers with its own run; never replace the displayed
      // parent with that child's status and identity.
      client.setQueryData<WorkflowRunRead>(qk.workflows.run(run.id), (current) =>
        current !== undefined && isRunTerminal(current.status) ? current : run,
      );
      refresh();
      void client.invalidateQueries({ queryKey: qk.workflows.runs(run.workflow_id) });
    },
    onError: (error, { workflowRunId }) => {
      toast.error(getErrorMessage(error, tErrors));
      // A duplicate answer, expiry or cancellation can have moved the run on.
      refresh();
      if (workflowRunId !== runId) {
        void client.invalidateQueries({ queryKey: qk.workflows.run(workflowRunId) });
      }
    },
  });
  return { questions, error: query.error, refetch: query.refetch, answer };
}
