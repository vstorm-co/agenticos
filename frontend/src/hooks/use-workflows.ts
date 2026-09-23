"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { WorkflowCreate, WorkflowDraftUpdate, WorkflowPublish } from "@/lib/workflows/types";
import {
  createWorkflow,
  getNodeCatalog,
  getWorkflow,
  listWorkflowVersions,
  listWorkflows,
  publishWorkflow,
  updateWorkflowDraft,
} from "@/lib/workflows/workflows-api";

/**
 * The workflow registry — the list and the create mutation.
 *
 * Mutations invalidate rather than patch: a create returns a fresh draft row and
 * guessing the list's new shape is how a stale registry shows.
 */
export function useWorkflows({ enabled = true }: { enabled?: boolean } = {}) {
  const t = useTranslations("workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.list(),
    queryFn: () => listWorkflows(),
    // How a surface without workflows:view stays out of the network log.
    enabled,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.workflows.all() }),
    [queryClient],
  );

  const create = useMutation({
    mutationFn: (input: WorkflowCreate) => createWorkflow(input),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
    onError: (err) => toast.error(getErrorMessage(err, tErrors)),
  });

  return {
    workflows: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    create,
  };
}

/**
 * One workflow with the graph currently being edited, plus the draft-save and
 * publish mutations.
 *
 * `saveDraft` is deliberately quiet: the autosave leaf owns its own conflict
 * handling (a `409` surfaces the store's conflict banner), so a toast here would
 * fight it. `publish` toasts because it is an explicit, one-off action.
 */
export function useWorkflow(workflowId: string | null) {
  const t = useTranslations("workflows");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.detail(workflowId ?? ""),
    queryFn: () => getWorkflow(workflowId as string),
    enabled: !!workflowId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.workflows.all() }),
    [queryClient],
  );

  const saveDraft = useMutation({
    mutationFn: (update: WorkflowDraftUpdate) => updateWorkflowDraft(workflowId as string, update),
    onSuccess: invalidate,
  });

  const publish = useMutation({
    mutationFn: (input: WorkflowPublish) => publishWorkflow(workflowId as string, input),
    onSuccess: async (version) => {
      await invalidate();
      toast.success(t("publishedVersion", { version: version.version }));
    },
    onError: (err) => toast.error(getErrorMessage(err, tErrors)),
  });

  return { workflow: data, isLoading, error, saveDraft, publish };
}

/** Every published version of a workflow, newest first. */
export function useWorkflowVersions(workflowId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.workflows.versions(workflowId ?? ""),
    queryFn: () => listWorkflowVersions(workflowId as string),
    enabled: !!workflowId,
  });
  return { versions: data?.items ?? [], isLoading };
}

/**
 * Every registered node type, for the editor's palette.
 *
 * Cached indefinitely: the catalog changes when the backend is redeployed, not
 * while someone builds a workflow.
 */
export function useNodeCatalog() {
  const { data, isLoading } = useQuery({
    queryKey: qk.workflows.nodeCatalog(),
    queryFn: () => getNodeCatalog(),
    staleTime: Infinity,
  });
  return { nodes: data?.items ?? [], isLoading };
}
