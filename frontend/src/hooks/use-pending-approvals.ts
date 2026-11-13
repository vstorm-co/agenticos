"use client";

import { useApprovals } from "@/hooks/use-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { useWorkflowApprovals } from "@/hooks/use-workflow-approvals";
import { Perm } from "@/types/permissions";

/**
 * What waits on the caller's decision: agents' parked tool calls and workflow
 * steps asking for approval, the two queues Activity → Approvals shows.
 *
 * Read only for a caller holding `approvals:decide`, which both lists require;
 * anyone else waits on nothing here and makes no request.
 */
export function usePendingApprovals() {
  const { can } = usePermissions();
  const allowed = can(Perm.approvalsDecide);
  const tools = useApprovals({ enabled: allowed });
  const steps = useWorkflowApprovals({ enabled: allowed });
  return {
    tools: allowed ? tools.approvals : [],
    steps: allowed ? steps.approvals : [],
    count: allowed ? tools.total + steps.total : 0,
  };
}
