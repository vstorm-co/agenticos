"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  createLogAlert,
  deleteLogAlert,
  listLogAlerts,
  updateLogAlert,
} from "@/lib/workflows/log-alerts-api";
import type { LogAlertInput, LogAlertPatch } from "@/lib/workflows/types";
import { toastDone } from "@/lib/toast";

/**
 * A workflow's log alert rules, and the writes on them. `error` is set when the read
 * failed: not a workflow with no rules. A save that fails rejects its
 * `mutateAsync` and says nothing itself: the dialog names the field at fault. A
 * failed delete toasts the server's words.
 */
export function useWorkflowLogAlerts(workflowId: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = qk.workflows.logAlerts(workflowId);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: key,
    queryFn: () => listLogAlerts(workflowId),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const failed = (cause: unknown) => toast.error(getErrorMessage(cause, tErrors));

  const create = useMutation({
    mutationFn: (input: LogAlertInput) => createLogAlert(workflowId, input),
    onSuccess: () => {
      toastDone(t("alertSaved"));
      return refresh();
    },
  });
  const update = useMutation({
    mutationFn: (args: { ruleId: string; patch: LogAlertPatch }) =>
      updateLogAlert(workflowId, args.ruleId, args.patch),
    onSuccess: () => {
      toastDone(t("alertSaved"));
      return refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (ruleId: string) => deleteLogAlert(workflowId, ruleId),
    onSuccess: () => {
      toastDone(t("alertDeleted"));
      return refresh();
    },
    onError: failed,
  });

  return { rules: data ?? [], isLoading, error, refetch, create, update, remove, failed };
}
