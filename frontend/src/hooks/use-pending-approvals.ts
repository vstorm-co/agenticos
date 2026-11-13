"use client";

import { useApprovals } from "@/hooks/use-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { useWorkflowApprovals } from "@/hooks/use-workflow-approvals";
import { useAuthStore } from "@/stores/auth-store";
import { Perm } from "@/types/permissions";

/**
 * What waits on the caller's decision: agents' parked tool calls and workflow
 * steps asking for approval, the two queues Activity → Approvals shows.
 *
 * Read only for a caller holding `approvals:decide`, which both lists require;
 * anyone else waits on nothing here and makes no request. A step that names its
 * approvers waits only on them, so the others are left out - counted from the
 * queue's first page, which is what the inbox lists from.
 */
export function usePendingApprovals() {
  const { can } = usePermissions();
  const me = useAuthStore((state) => state.user?.id);
  const allowed = can(Perm.approvalsDecide);
  const tools = useApprovals({ enabled: allowed });
  const steps = useWorkflowApprovals({ enabled: allowed });
  const mine = steps.approvals.filter(
    (step) =>
      step.approver_user_ids.length === 0 ||
      (me !== undefined && step.approver_user_ids.includes(me)),
  );
  return {
    tools: allowed ? tools.approvals : [],
    steps: allowed ? mine : [],
    count: allowed ? tools.total + mine.length : 0,
  };
}
