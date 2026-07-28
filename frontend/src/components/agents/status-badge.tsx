import { Badge } from "@/components/ui";
import type { AgentStatus } from "@/types/agents";
import type { RunStatus } from "@/types/runs";

const AGENT_VARIANT: Record<AgentStatus, "default" | "secondary" | "outline"> = {
  published: "default",
  draft: "secondary",
  archived: "outline",
};

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <Badge variant={AGENT_VARIANT[status]}>{status}</Badge>;
}

/**
 * `budget_exceeded` reads as a warning, not an error.
 *
 * It is the platform working as designed, and colouring it like a crash makes
 * operators chase a problem that is not one.
 */
const RUN_VARIANT: Record<RunStatus, "default" | "secondary" | "outline" | "destructive"> = {
  completed: "default",
  running: "secondary",
  awaiting_approval: "secondary",
  budget_exceeded: "outline",
  cancelled: "outline",
  failed: "destructive",
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
  return <Badge variant={RUN_VARIANT[status]}>{RUN_LABEL[status]}</Badge>;
}
