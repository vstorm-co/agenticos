"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { decideWorkflowApproval, listWorkflowApprovals } from "@/lib/workflows/approvals-api";

/**
 * The requests workflow steps are waiting on, and deciding one.
 *
 * Read again every half minute like the tool approvals queue, since a step
 * asks whenever its run reaches it. A decision refreshes every workflow read -
 * the run it wakes is on some other page's screen too.
 */
export function useWorkflowApprovals(options?: { enabled?: boolean }) {
  const t = useTranslations("pages.runs");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.approvals(),
    queryFn: listWorkflowApprovals,
    refetchInterval: 30_000,
    enabled: options?.enabled ?? true,
  });
  const decide = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      decideWorkflowApproval(id, approved),
    onSuccess: async (approval) => {
      await queryClient.invalidateQueries({ queryKey: qk.workflows.all() });
      toast.success(approval.status === "approved" ? t("decisionApproved") : t("decisionRejected"));
    },
    onError: (failure) => toast.error(getErrorMessage(failure, tErrors)),
  });
  return { approvals: data?.items ?? [], total: data?.total ?? 0, isLoading, error, decide };
}
