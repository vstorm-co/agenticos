"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { WorkflowDetail, WorkflowSettings, WorkflowUpdate } from "@/lib/workflows/types";
import {
  archiveWorkflow,
  deleteWorkflow,
  setWorkflowActive,
  unarchiveWorkflow,
  updateWorkflow,
  updateWorkflowSettings,
} from "@/lib/workflows/workflows-api";

/**
 * What can be done to a workflow as a whole - rename or tag it, change its
 * settings, switch its trigger, archive, restore or delete it - from its editor
 * or its card.
 *
 * Each answer that carries the workflow is written into its detail, so the
 * header shows the change without a refetch, and the list is refreshed. A
 * refusal is toasted: none of these has a form of its own to show it in.
 */
export function useWorkflowActions() {
  const t = useTranslations("pages.workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const fail = (error: unknown) => toast.error(getErrorMessage(error, tErrors));

  const settle = async (detail: WorkflowDetail) => {
    queryClient.setQueryData(qk.workflows.detail(detail.id), detail);
    await queryClient.invalidateQueries({ queryKey: qk.workflows.list() });
    // The trigger sheet reads the exposure on its own, and the switch moves it.
    await queryClient.invalidateQueries({ queryKey: qk.workflows.exposure(detail.id) });
  };

  const update = useMutation({
    mutationFn: ({ id, update }: { id: string; update: WorkflowUpdate }) =>
      updateWorkflow(id, update),
    onSuccess: settle,
    onError: fail,
  });

  const saveSettings = useMutation({
    mutationFn: ({ id, settings }: { id: string; settings: WorkflowSettings }) =>
      updateWorkflowSettings(id, settings),
    onSuccess: async (detail) => {
      await settle(detail);
      toast.success(t("settingsSaved"));
    },
    onError: fail,
  });

  const setActive = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => setWorkflowActive(id, active),
    onSuccess: async (detail) => {
      await settle(detail);
      toast.success(detail.trigger_active ? t("activeTurnedOn") : t("activeTurnedOff"));
    },
    onError: fail,
  });

  const archive = useMutation({
    mutationFn: (id: string) => archiveWorkflow(id),
    onSuccess: async (detail) => {
      await settle(detail);
      toast.success(t("archivedToast"));
    },
    onError: fail,
  });

  const unarchive = useMutation({
    mutationFn: (id: string) => unarchiveWorkflow(id),
    onSuccess: async (detail) => {
      await settle(detail);
      toast.success(t("restoredToast"));
    },
    onError: fail,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteWorkflow(id),
    onSuccess: async (_answer, id) => {
      queryClient.removeQueries({ queryKey: qk.workflows.detail(id) });
      await queryClient.invalidateQueries({ queryKey: qk.workflows.list() });
      toast.success(t("deletedToast"));
    },
    onError: fail,
  });

  return { update, saveSettings, setActive, archive, unarchive, remove };
}
