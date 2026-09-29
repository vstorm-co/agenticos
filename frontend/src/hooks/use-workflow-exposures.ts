"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  createWorkflowExposure,
  deleteWorkflowExposure,
  listWorkflowExposures,
  rotateWorkflowExposureSecret,
  updateWorkflowExposure,
} from "@/lib/workflows/exposures-api";
import type { WorkflowExposureCreate, WorkflowExposureUpdate } from "@/lib/workflows/types";

/**
 * A workflow's webhooks and schedules, and every write to them.
 *
 * Create and rotate resolve with the signing secret the server returns once;
 * the caller shows it, since nothing reads it back later.
 */
export function useWorkflowExposures(workflowId: string) {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const key = qk.workflows.exposures(workflowId);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => listWorkflowExposures(workflowId),
  });
  const create = useMutation({
    mutationFn: (body: WorkflowExposureCreate) => createWorkflowExposure(workflowId, body),
    onSuccess: () => {
      refresh();
      toast.success(t("exposureCreated"));
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: WorkflowExposureUpdate }) =>
      updateWorkflowExposure(workflowId, id, body),
    onSuccess: refresh,
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteWorkflowExposure(workflowId, id),
    onSuccess: () => {
      refresh();
      toast.success(t("exposureDeleted"));
    },
    onError: fail,
  });
  const rotate = useMutation({
    mutationFn: (id: string) => rotateWorkflowExposureSecret(workflowId, id),
    onSuccess: refresh,
    onError: fail,
  });
  return { exposures: data?.items ?? [], isLoading, create, update, remove, rotate };
}
