"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import type { UsableMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import { getWorkflow, listWorkflowMcpConnections } from "@/lib/workflows/workflows-api";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/**
 * The organization's MCP servers as a step of the open workflow picks one.
 *
 * Read for whoever may edit this workflow - by role or by a grant on it, which is
 * the page's own `can_edit` - because that is who publishing a step is open to.
 * `connections` is `null` while loading and for a member who may not edit it:
 * "not known", never "none"; `canRead` says which.
 *
 * Always asked again on focus: a manager tests a server or adds one in another
 * tab, and an editor who cannot do either should see it without a reload.
 */
export function useUsableMcpConnections(enabled = true): {
  connections: UsableMcpConnectionRecord[] | null;
  isLoading: boolean;
  /** Whether this member may edit the open workflow, so may read the list. */
  canRead: boolean;
} {
  const workflowId = useWorkflowEditorStore((state) => state.workflowId);
  // The page's own cache entry, so this adds no request of its own once it has loaded.
  const { data: workflow } = useQuery({
    queryKey: qk.workflows.detail(workflowId ?? ""),
    queryFn: () => getWorkflow(workflowId as string),
    enabled: workflowId !== null,
  });
  const canRead = workflow?.can_edit === true;
  const { data, isLoading } = useQuery({
    queryKey: qk.mcpConnections.usable(workflowId ?? ""),
    queryFn: () => listWorkflowMcpConnections(workflowId as string),
    enabled: enabled && canRead && workflowId !== null,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
  return {
    connections: canRead ? (data ?? null) : null,
    isLoading: canRead && isLoading,
    canRead,
  };
}
