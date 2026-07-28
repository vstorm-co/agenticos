import { Badge } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { AgentStatus } from "@/types/agents";
import type { RunStatus } from "@/types/runs";

/**
 * Status as a dot beside quiet text, never a filled chip.
 *
 * A gallery of solid chips is a page shouting six colours; a coloured dot
 * carries the same fact at a fraction of the volume, and the label stays
 * readable in both themes because it is always plain foreground text. The dot
 * colours are the platform's status tones - success, warning, destructive -
 * plus muted for the states that are simply "not on".
 */
function StatusDot({ className }: { className: string }) {
  return <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", className)} />;
}

const AGENT_DOT: Record<AgentStatus, string> = {
  published: "bg-success",
  draft: "bg-warning",
  archived: "bg-muted-foreground/50",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <StatusDot className={AGENT_DOT[status]} />
      {status}
    </Badge>
  );
}

/**
 * `budget_exceeded` reads as a warning, not an error.
 *
 * It is the platform working as designed, and colouring it like a crash makes
 * operators chase a problem that is not one.
 */
const RUN_DOT: Record<RunStatus, string> = {
  completed: "bg-success",
  running: "bg-brand animate-pulse",
  awaiting_approval: "bg-warning",
  budget_exceeded: "bg-warning",
  cancelled: "bg-muted-foreground/50",
  failed: "bg-destructive",
};

const RUN_LABEL: Record<RunStatus, string> = {
  completed: "completed",
  running: "running",
  awaiting_approval: "waiting for approval",
  budget_exceeded: "stopped by budget",
  cancelled: "cancelled",
  failed: "failed",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <StatusDot className={RUN_DOT[status]} />
      {RUN_LABEL[status]}
    </Badge>
  );
}
