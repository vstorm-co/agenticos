"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  getWorkflowExposure,
  listWorkflowExposures,
  renewWorkflowFormLink,
  rotateWorkflowExposureSecret,
  updateWorkflowExposure,
} from "@/lib/workflows/exposures-api";

/**
 * A workflow's webhook, schedule or form - what its live trigger node switched
 * on - and the writes made beside the graph: pausing, rotating a webhook's
 * secret and replacing a form's link. Rotate resolves with the secret the server
 * returns once; the caller shows it, since nothing reads it back later.
 */
export function useWorkflowExposure(workflowId: string, trigger?: string | null, nodeId?: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = [...qk.workflows.exposure(workflowId), ...(trigger ? ["all"] : [])];
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: async () =>
      trigger ? listWorkflowExposures(workflowId) : getWorkflowExposure(workflowId),
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
  const renewLink = useMutation({
    mutationFn: (id: string) => renewWorkflowFormLink(workflowId, id),
    onSuccess: () => {
      refresh();
      toast.success(t("formLinkRenewed"));
    },
    onError: fail,
  });
  const adapter = trigger?.replace("trigger.", "").replace("channel_message", "channel");
  const exposure = Array.isArray(data)
    ? (data.find(
        (item) =>
          item.adapter === adapter && (nodeId === undefined || item.node_instance_id === nodeId),
      ) ?? null)
    : (data ?? null);
  return { exposure, isLoading, setActive, rotate, renewLink };
}
