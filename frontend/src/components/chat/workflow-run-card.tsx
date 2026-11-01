"use client";

import Link from "next/link";
import { ArrowUpRight, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { ROUTES } from "@/lib/constants";
import type { WorkflowRunStatus } from "@/lib/workflows/types";
import type { WorkflowRunPart } from "@/types";

/**
 * A workflow answering a chat turn: which workflow, how its run is going or
 * ended, and a way to its steps.
 *
 * The same card live and after a reload - live, the chat socket moves its
 * status; read back, the stored `workflow_run` entry carries where it ended.
 * The name is the one recorded when it answered, so the card needs no query
 * of its own.
 */
export function WorkflowRunCard({ run }: { run: WorkflowRunPart }) {
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
