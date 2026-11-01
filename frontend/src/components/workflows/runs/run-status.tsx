import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { NodeRunStatus, WorkflowRunStatus } from "@/lib/workflows/types";

/**
 * A run's and a step's status as a dot beside quiet text - the console's
 * status idiom (`AgentStatusBadge`, `RunStatusBadge`), in the platform's status
 * tones. A pause a person has to act on is a warning, not a failure.
 */
export const RUN_DOT: Record<WorkflowRunStatus, string> = {
  queued: "bg-muted-foreground/50",
  running: "bg-brand animate-pulse",
  waiting_approval: "bg-warning",
  waiting_retry: "bg-warning animate-pulse",
  needs_attention: "bg-warning",
  budget_exceeded: "bg-warning",
  failed: "bg-destructive",
  cancelled: "bg-muted-foreground/50",
  succeeded: "bg-success",
};

export const NODE_DOT: Record<NodeRunStatus, string> = {
  pending: "bg-muted-foreground/50",
  running: "bg-brand animate-pulse",
  waiting: "bg-warning",
  needs_attention: "bg-warning",
  succeeded: "bg-success",
  failed: "bg-destructive",
  skipped: "bg-muted-foreground/30",
  cancelled: "bg-muted-foreground/50",
};

function Dot({ className }: { className: string }) {
  return <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", className)} />;
}

export function WorkflowRunStatusBadge({ status }: { status: WorkflowRunStatus }) {
  const t = useTranslations("pages.workflows.runStatus");
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <Dot className={RUN_DOT[status]} />
      {t(status)}
    </Badge>
  );
}

export function NodeRunStatusLabel({ status }: { status: NodeRunStatus }) {
  const t = useTranslations("pages.workflows.nodeStatus");
  return (
    <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
      <Dot className={NODE_DOT[status]} />
      {t(status)}
    </span>
  );
}
