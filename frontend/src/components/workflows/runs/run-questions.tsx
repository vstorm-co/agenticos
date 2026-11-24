"use client";

import { useTranslations } from "next-intl";

import { Button, QuestionPrompt } from "@/components/ui";
import { useWorkflowRunQuestions } from "@/hooks/use-workflow-questions";
import { toAskUserQuestions } from "@/lib/ask-user-questions";
import type { WorkflowQuestionRead, WorkflowQuestionResponses } from "@/lib/workflows/types";
import type { AskUserAnswer } from "@/types/chat";

/** One shared answer surface for the run page and its originating chat card. */
export function WorkflowRunQuestions({ runId }: { runId: string }) {
  const t = useTranslations("pages.workflows");
  const { questions, error, refetch, answer } = useWorkflowRunQuestions(runId);
  if (error !== null) {
    return (
      <div role="alert" className="space-y-2 text-sm">
        <p>{t("runQuestionsFailed")}</p>
        <Button size="sm" variant="outline" onClick={() => void refetch()}>
          {t("runQuestionsRetry")}
        </Button>
      </div>
    );
  }
  if (questions.length === 0) return null;
  return (
    <div className="space-y-3">
      <p data-tour="workflow-run-questions" className="text-sm font-medium">
        {t("runQuestionsTitle")}
      </p>
      {questions.map((entry) => (
        <QuestionPrompt
          key={`${entry.node_run_id}-${entry.questions.map((call) => call.tool_call_id).join("-")}`}
          questions={toAskUserQuestions(entry.questions.flatMap((call) => call.questions))}
          disabled={answer.isPending}
          onComplete={(answers) =>
            answer.mutate({
              workflowRunId: entry.workflow_run_id,
              nodeRunId: entry.node_run_id,
              responses: responsesFor(entry, answers),
            })
          }
        />
      ))}
    </div>
  );
}

/** Parallel tool calls are answered together, under the original tool call ids. */
function responsesFor(
  entry: WorkflowQuestionRead,
  answers: AskUserAnswer[],
): WorkflowQuestionResponses {
  let offset = 0;
  return Object.fromEntries(
    entry.questions.map((call) => {
      const result = answers.slice(offset, offset + call.questions.length);
      offset += call.questions.length;
      return [call.tool_call_id, result] as const;
    }),
  );
}
