"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  getWorkflowExposure,
  rotateWorkflowExposureSecret,
  updateWorkflowExposure,
} from "@/lib/workflows/exposures-api";

/**
 * A workflow's webhook or schedule - what its live trigger node switched on -
 * and the two writes made beside the graph: pausing, and rotating a webhook's
 * secret. Rotate resolves with the secret the server returns once; the caller
 * shows it, since nothing reads it back later.
 */
export function useWorkflowExposure(workflowId: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = qk.workflows.exposure(workflowId);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => getWorkflowExposure(workflowId),
  });
  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      updateWorkflowExposure(workflowId, id, { is_active: active }),
    onSuccess: (exposure) => {
      refresh();
      // The editor's Active switch and the list's card read the same state.
      void queryClient.invalidateQueries({ queryKey: qk.workflows.detail(workflowId) });
      void queryClient.invalidateQueries({ queryKey: qk.workflows.list() });
      toast.success(exposure.is_active ? t("triggerResumed") : t("triggerPaused"));
    },
    onError: fail,
  });
  const rotate = useMutation({
    mutationFn: (id: string) => rotateWorkflowExposureSecret(workflowId, id),
    onSuccess: refresh,
    onError: fail,
  });
  return { exposure: data ?? null, isLoading, setActive, rotate };
}
