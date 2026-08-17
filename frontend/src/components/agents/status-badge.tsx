import { useTranslations } from "next-intl";

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

/**
 * The word for a status, as a key rather than the word.
 *
 * The badge used to render the enum member itself, which is English by accident
 * of the API rather than by choice - and `RUN_LABEL` below did carry the word,
 * while `agents.failed` and `chat.steps.awaitingApproval` already held it in the
 * catalog for somebody else to read (#425).
 */
const AGENT_LABEL: Record<AgentStatus, string> = {
  published: "statusPublished",
  draft: "statusDraft",
  archived: "statusArchived",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  const t = useTranslations("agents");
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <StatusDot className={AGENT_DOT[status]} />
      {t(AGENT_LABEL[status])}
    </Badge>
  );
}

/**
 * `budget_exceeded` and `guardrail_blocked` read as a warning, not an error.
 *
 * Each is the platform working as designed - a cap reached, a rule enforced -
 * and colouring it like a crash makes operators chase a problem that is not one.
 */
const RUN_DOT: Record<RunStatus, string> = {
  completed: "bg-success",
  running: "bg-brand animate-pulse",
  awaiting_approval: "bg-warning",
  budget_exceeded: "bg-warning",
  guardrail_blocked: "bg-warning",
  cancelled: "bg-muted-foreground/50",
  failed: "bg-destructive",
};

// Exported for the run-history filter, whose Select options are these same
// words - one catalog key per status, never a second copy.
export const RUN_LABEL: Record<RunStatus, string> = {
  completed: "runCompleted",
  running: "runRunning",
  awaiting_approval: "runAwaitingApproval",
  budget_exceeded: "runBudgetExceeded",
  guardrail_blocked: "runGuardrailBlocked",
  cancelled: "runCancelled",
  failed: "runFailed",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const t = useTranslations("agents");
  return (
    <Badge variant="outline" className="text-muted-foreground">
      <StatusDot className={RUN_DOT[status]} />
      {t(RUN_LABEL[status])}
    </Badge>
  );
}
