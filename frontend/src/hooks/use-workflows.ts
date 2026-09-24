"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  WorkflowDraftUpdate,
  WorkflowGraph,
  WorkflowPublish,
  WorkflowRead,
} from "@/lib/workflows/types";
import {
  createWorkflow,
  getNodeCatalog,
  getWorkflow,
  getWorkflowVersion,
  listWorkflowVersions,
  listWorkflows,
  publishWorkflow,
  updateWorkflowDraft,
} from "@/lib/workflows/workflows-api";

/** Create a workflow, optionally seeding its draft graph — a template, or a copy. */
export interface WorkflowSeed {
  name: string;
  graph?: WorkflowGraph | null;
}

/**
 * Seed a freshly created workflow's draft graph, if a graph was given.
 *
 * `createWorkflow` always makes an *empty* draft, so a template or a duplicate is
 * a create followed by one draft write against the revision the create returned
 * (0 for a new row). A blank create passes no graph and skips the write.
 */
async function seedGraph(
  workflow: WorkflowRead,
  graph: WorkflowGraph | null | undefined,
): Promise<WorkflowRead> {
  if (graph) {
    await updateWorkflowDraft(workflow.id, {
      graph,
      expected_revision: workflow.draft_revision,
    });
  }
  return workflow;
}

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
    mutationFn: async ({ name, graph }: WorkflowSeed) =>
      seedGraph(await createWorkflow({ name }), graph),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("created"));
    },
    onError: (err) => toast.error(getErrorMessage(err, tErrors)),
  });

  // Duplicate copies a source workflow's *current draft* graph into a brand-new
  // workflow (never a version): read the source's draft, create a fresh row, seed
  // it with what was read.
  const duplicate = useMutation({
    mutationFn: async ({ sourceId, name }: { sourceId: string; name: string }) => {
      const source = await getWorkflow(sourceId);
      return seedGraph(await createWorkflow({ name }), source.draft_graph);
    },
    onSuccess: async () => {
      await invalidate();
      toast.success(t("duplicated"));
    },
    onError: (err) => toast.error(getErrorMessage(err, tErrors)),
  });

  return {
    workflows: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    create,
    duplicate,
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

/** Every published version of a workflow, newest first. Lean — no graphs. */
export function useWorkflowVersions(workflowId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.workflows.versions(workflowId ?? ""),
    queryFn: () => listWorkflowVersions(workflowId as string),
    enabled: !!workflowId,
  });
  return { versions: data?.items ?? [], isLoading };
}

/**
 * One published version with its frozen graph, fetched on demand.
 *
 * Enabled only while a version is selected for preview, so the graph is never
 * pulled until someone opens a version — the list stays lean and the detail rides
 * its own query, cached per version id (a frozen version never changes).
 */
export function useWorkflowVersion(workflowId: string, versionId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.workflows.version(workflowId, versionId ?? ""),
    queryFn: () => getWorkflowVersion(workflowId, versionId as string),
    enabled: !!versionId,
    staleTime: Infinity,
  });
  return { version: data, isLoading, error };
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
