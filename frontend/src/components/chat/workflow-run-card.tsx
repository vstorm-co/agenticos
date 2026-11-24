"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { WorkflowIcon as Workflow } from "@/components/icons/product-icons";
import { useTranslations } from "next-intl";

import { WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { WorkflowRunQuestions } from "@/components/workflows/runs/run-questions";
import { useWorkflowChatRun } from "@/hooks/use-workflow-questions";
import { isRunTerminal } from "@/lib/workflows/types";
import { ROUTES } from "@/lib/constants";
import type { WorkflowRunStatus } from "@/lib/workflows/types";
import type { WorkflowRunPart } from "@/types";

/**
 * A workflow answering a chat turn: which workflow, how its run is going or
 * ended, and a way to its steps.
 *
 * The same card live and after a reload - live, the chat socket moves its
 * status; read back, the stored `workflow_run` entry carries where it ended.
 * The name is the one recorded when it answered. A live card also reads the
 * saved run so questions and later state survive a disconnected chat socket.
 */
export function WorkflowRunCard({ run }: { run: WorkflowRunPart }) {
  if (run.runId !== null && !isRunTerminal(run.status as WorkflowRunStatus)) {
    return <LiveWorkflowRunCard run={run} runId={run.runId} />;
  }
  return <WorkflowRunCardView run={run} />;
}

function LiveWorkflowRunCard({ run, runId }: { run: WorkflowRunPart; runId: string }) {
  const { data } = useWorkflowChatRun(runId);
  const status = data?.status ?? run.status;
  const error = data?.error?.message ?? run.error;
  return (
    <WorkflowRunCardView run={{ ...run, status, error }}>
      {!isRunTerminal(status as WorkflowRunStatus) && <WorkflowRunQuestions runId={runId} />}
    </WorkflowRunCardView>
  );
}

function WorkflowRunCardView({ run, children }: { run: WorkflowRunPart; children?: ReactNode }) {
  const t = useTranslations("chat.workflowRun");
  return (
    <div className="bg-card flex w-full max-w-md items-start gap-3 rounded-xl border p-3">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-700 dark:text-amber-300">
        <Workflow aria-hidden="true" className="size-4" />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-medium">{run.workflowName ?? t("unnamed")}</p>
          <WorkflowRunStatusBadge status={run.status as WorkflowRunStatus} />
        </div>
        {children}
        {run.error && <p className="text-destructive text-xs">{run.error}</p>}
        {run.runId && (
          <Link
            href={ROUTES.WORKFLOW_RUN_DETAIL(run.workflowId, run.runId)}
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
          >
            {t("viewSteps")}
            <ArrowUpRight aria-hidden="true" className="size-3" />
          </Link>
        )}
      </div>
    </div>
  );
}
