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
 * anyone else waits on nothing here and makes no request. A step waits only on
 * its approval audience - its named approvers and the deciding members of its
 * approver groups - which the server answers as `can_decide`. A row without it
 * falls back to the named approvers alone. Counted from the queue's first page,
 * which is what the inbox lists from. While either queue loads or after one
 * fails, nothing here is known, and `isLoading` / `error` say so.
 */
export function usePendingApprovals() {
  const { can } = usePermissions();
  const me = useAuthStore((state) => state.user?.id);
  const allowed = can(Perm.approvalsDecide);
  const tools = useApprovals({ enabled: allowed });
  const steps = useWorkflowApprovals({ enabled: allowed });
  const mine = steps.approvals.filter(
    (step) =>
      step.can_decide ??
      (step.approver_user_ids.length === 0 ||
        (me !== undefined && step.approver_user_ids.includes(me))),
  );
  return {
    tools: allowed ? tools.approvals : [],
    steps: allowed ? mine : [],
    count: allowed ? tools.total + mine.length : 0,
    isLoading: allowed && (tools.isLoading || steps.isLoading),
    error: allowed ? (tools.error ?? steps.error) : null,
    refetch: allowed
      ? () => Promise.all([tools.refetch(), steps.refetch()])
      : () => Promise.resolve([]),
  };
}
