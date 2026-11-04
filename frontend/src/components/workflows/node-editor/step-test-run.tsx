"use client";

import { AlertTriangle, Square } from "lucide-react";
import { useTranslations } from "next-intl";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui";
import { useWorkflowRun } from "@/hooks";
import { isRunTerminal, type Uuid } from "@/lib/workflows/types";

/** What a step's own run ended as when it never ran: why, as a message key. */
function missedReason(runStatus: string, nodeStatus: string | undefined): string | null {
  if (nodeStatus === "succeeded" || nodeStatus === "failed") return null;
  if (runStatus === "cancelled") return "stepTestStopped";
  return nodeStatus === "skipped" ? "stepTestSkipped" : "stepTestNotReached";
}

/**
 * Beside **Test step**, for the step test last started from this step: **Stop**
 * while its run is going - a click by mistake, or a run taking longer than it is
 * worth - and, once it has ended without this step running, a warning saying
 * why: the run went down another branch, ended before it, or was stopped.
 * Otherwise nothing: a step that ran shows its output, and one that failed, its
 * error.
 */
export function StepTestRun({ runId, nodeId }: { runId: string; nodeId: Uuid }) {
  const t = useTranslations("workflows");
  const { run, nodes, cancel } = useWorkflowRun(runId);
  if (run === null) return null;

  if (!isRunTerminal(run.status)) {
    return (
      <button
        type="button"
        aria-label={t("stepTestStop")}
        title={t("stepTestStopHint")}
        disabled={cancel.isPending}
        onClick={() => cancel.mutate()}
        className="text-destructive hover:bg-destructive/10 focus-visible:ring-ring flex size-7 items-center justify-center rounded-md outline-none focus-visible:ring-2 disabled:opacity-50"
      >
        <Square aria-hidden="true" className="size-3.5 fill-current" />
      </button>
    );
  }

  const own = nodes.find(
    (candidate) => candidate.node_instance_id === nodeId && candidate.scope_path.length === 0,
  );
  const reason = missedReason(run.status, own?.status);
  if (reason === null) return null;
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          {/* A button only so a keyboard can reach the reason; it does nothing else. */}
          <button
            type="button"
            aria-label={t(reason)}
            className="text-warning focus-visible:ring-ring flex size-7 items-center justify-center rounded-md outline-none focus-visible:ring-2"
          >
            <AlertTriangle aria-hidden="true" className="size-4" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{t(reason)}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
