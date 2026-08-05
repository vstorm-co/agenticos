"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { problemList } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { getErrorMessage } from "@/lib/utils";
import type {
  Agent,
  AgentDetail,
  AgentList,
  AgentSpec,
  AgentVersion,
  AgentVersionDetail,
  AgentVersionList,
  CapabilityCatalog,
} from "@/types/agents";

/**
 * The agent registry.
 *
 * Mutations invalidate rather than patch the cache. An agent's status and
 * version pointer change as a side effect of publishing, and guessing what the
 * server did is how a Builder starts showing a draft as published.
 */
export function useAgents({ includeArchived = false }: { includeArchived?: boolean } = {}) {
  const queryClient = useQueryClient();

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.agents.list(includeArchived),
    queryFn: () =>
      apiClient.get<AgentList>(
        "/agents",
        includeArchived ? { params: { include_archived: "true" } } : undefined,
      ),
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
    [queryClient],
  );

  // Alone among the mutations here, this one does not toast its failure. The
  // things that stop an agent being created - the handle is taken, the name is
  // too long - are things the reader can fix in the dialog they are looking at,
  // so the dialog decides what to do with them (see `submitFailure`). A toast
  // here would put the same message somewhere it cannot be acted on, and then
  // take it away again.
  const create = useMutation({
    mutationFn: (spec: AgentSpec) => apiClient.post<Agent>("/agents", { spec }),
    onSuccess: async (agent) => {
      await invalidate();
      toast.success(`Created ${agent.name}`);
    },
  });

  /**
   * Copy an agent's draft into a new one.
   *
   * The name is the server's to derive - it owns the handle that has to be
   * unique - so cloning takes no input and never fails on a name the caller was
   * not offered a chance to choose.
   */
  const clone = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/clone`, {}),
    onSuccess: async (agent) => {
      await invalidate();
      toast.success(`Created ${agent.name} - a draft, nothing published yet`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const archive = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/archive`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success("Agent archived. Its history and runs are kept.");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const unarchive = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/unarchive`, {}),
    onSuccess: async (agent) => {
      await invalidate();
      toast.success(
        agent.status === "published"
          ? `${agent.name} is live again`
          : `${agent.name} is back as a draft - publish it to run it`,
      );
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/agents/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success("Agent deleted");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return {
    agents: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refetch,
    // Stale data is served while a refetch is in flight, so "this agent is not
    // in the list" can mean "not yet". Anything that would act on an absence
    // has to know the difference - see the chat's agent picker.
    isFetching,
    create,
    clone,
    archive,
    unarchive,
    remove,
  };
}

/** One agent, with the spec currently being edited. */
export function useAgent(agentId: string | null) {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.agents.detail(agentId ?? ""),
    queryFn: () => apiClient.get<AgentDetail>(`/agents/${agentId}`),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
    [queryClient],
  );

  const saveDraft = useMutation({
    mutationFn: (spec: AgentSpec) => apiClient.put<Agent>(`/agents/${agentId}/draft`, { spec }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  /**
   * Check the draft without publishing.
   *
   * Returns the list of problems rather than throwing: the Builder shows them
   * next to the fields that caused them, and a rejected draft is a normal state
   * to be in while editing.
   */
  const validate = useCallback(async (): Promise<string[]> => {
    try {
      await apiClient.post<void>(`/agents/${agentId}/validate`, {});
      return [];
    } catch (error) {
      // This read used to be `error.details`, a property `ApiError` has never
      // had, so the list the backend goes out of its way to report in full was
      // always thrown away and replaced with one line. `problemList` reads the
      // envelope; the fallback is for the failures that are not a verdict on
      // the spec at all - a refused permission, a dropped connection.
      return problemList(error) ?? [getErrorMessage(error)];
    }
  }, [agentId]);

  const publish = useMutation({
    mutationFn: (note: string | null) =>
      apiClient.post<{ version: number }>(`/agents/${agentId}/publish`, { note }),
    onSuccess: async (version) => {
      await invalidate();
      toast.success(`Published v${version.version}`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  const rollback = useMutation({
    mutationFn: (versionId: string) =>
      apiClient.post<AgentVersion>(`/agents/${agentId}/rollback`, { version_id: versionId }),
    onSuccess: async (version) => {
      await invalidate();
      // Rolling back publishes a *new* version rather than moving a pointer
      // backwards, so run history keeps telling the truth about what was live.
      toast.success(`Rolled back - now running v${version.version}`);
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  /**
   * Replace the agent's picture.
   *
   * Not part of the spec and so not part of the draft: uploading takes effect
   * at once rather than waiting for a publish, because a picture cannot change
   * what the agent does and versioning one would put a diff in a reviewed
   * artifact for something nobody reviews.
   */
  const setAvatar = useMutation({
    mutationFn: (file: File) => apiClient.upload<Agent>(`/agents/${agentId}/avatar`, file),
    onSuccess: async () => {
      await invalidate();
      toast.success("Avatar updated");
    },
    onError: (error) => toast.error(getErrorMessage(error)),
  });

  return { agent: data, isLoading, saveDraft, validate, publish, rollback, setAvatar };
}

export function useAgentVersions(agentId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.agents.versions(agentId ?? ""),
    queryFn: () => apiClient.get<AgentVersionList>(`/agents/${agentId}/versions`),
    enabled: !!agentId,
  });
  return { versions: data?.items ?? [], isLoading };
}

/**
 * One version with the spec it froze.
 *
 * Fetched per version rather than with the list: the list is a timeline, and a
 * spec is the whole configuration of an agent. A version never changes once
 * published, so this is cached for the session - the one query in this file
 * where that is a fact about the data and not an optimism.
 */
export function useAgentVersion(agentId: string | null, versionId: string | null) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.agents.version(agentId ?? "", versionId ?? ""),
    queryFn: () => apiClient.get<AgentVersionDetail>(`/agents/${agentId}/versions/${versionId}`),
    enabled: !!agentId && !!versionId,
    staleTime: Infinity,
  });
  return { version: data, isLoading, error };
}

/**
 * Everything an agent can be given.
 *
 * Cached indefinitely: the catalog changes when the backend is redeployed, not
 * while someone is building an agent.
 */
export function useCapabilityCatalog() {
  const { data, isLoading } = useQuery({
    queryKey: qk.agents.capabilityCatalog(),
    queryFn: () => apiClient.get<CapabilityCatalog>("/agents/capabilities"),
    staleTime: Infinity,
  });
  return { capabilities: data?.items ?? [], isLoading };
}
