"use client";

import { useCallback } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import { fieldProblems, getErrorMessage, problemList } from "@/lib/api-error";
import type { FieldProblem } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type {
  Agent,
  AgentDetail,
  AgentList,
  AgentSpec,
  AgentVersion,
  AgentVersionDetail,
  AgentVersionList,
  CapabilityCatalog,
  DelegationTree,
  SpecialistSpec,
} from "@/types/agents";

/** What promoting a specialist sends: the specialist whole, plus the model a null
 * `model_profile_id` falls back to - the parent's, since a standalone agent has no
 * parent. Mirrors the backend `SpecialistPromote`. */
export interface PromoteSpecialist {
  specialist: SpecialistSpec;
  fallbackModelProfileId: string | null;
}

/**
 * The agent registry.
 *
 * Mutations invalidate rather than patch the cache. An agent's status and
 * version pointer change as a side effect of publishing, and guessing what the
 * server did is how a Builder starts showing a draft as published.
 */
export function useAgents({
  includeArchived = false,
  enabled = true,
}: { includeArchived?: boolean; enabled?: boolean } = {}) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("agents");
  const queryClient = useQueryClient();

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: qk.agents.list(includeArchived),
    queryFn: () =>
      apiClient.get<AgentList>(
        "/agents",
        includeArchived ? { params: { include_archived: "true" } } : undefined,
      ),
    // How a surface without agents:view stays out of the network log - the
    // run table's agent column and the filter bar both read this gated.
    enabled,
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
      toast.success(t("created", { name: agent.name }));
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
      toast.success(t("createdDraft", { name: agent.name }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  /**
   * Keep a specialist by making it a draft agent owned by whoever promoted it.
   *
   * The one honest exit for a specialist that earned its own version - a dynamic
   * one, which is persisted nowhere, or an inline one that should be its own agent.
   * It creates a draft and stops: no publish, no pinning it back onto a parent, no
   * removing the inline specialist it came from. The name can collide with an
   * existing handle, so the caller handles failure rather than the hook.
   */
  const promote = useMutation({
    mutationFn: ({ specialist, fallbackModelProfileId }: PromoteSpecialist) =>
      apiClient.post<Agent>("/agents/promote", {
        specialist,
        fallback_model_profile_id: fallbackModelProfileId,
      }),
    onSuccess: async () => {
      await invalidate();
    },
  });

  const archive = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/archive`, {}),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("archived"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const unarchive = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/unarchive`, {}),
    onSuccess: async (agent) => {
      await invalidate();
      toast.success(
        agent.status === "published"
          ? t("liveAgain", { name: agent.name })
          : t("backAsDraft", { name: agent.name }),
      );
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/agents/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("deleted"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
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
    promote,
    archive,
    unarchive,
    remove,
  };
}

/**
 * Why a spec cannot be published, in the two places the Builder shows it.
 *
 * `fields` is a subset of what `problems` says, not a second answer: every
 * problem that names an input also gets a line, because the page lists them all
 * above the form and only one of the Builder's forms is generated from a schema.
 */
export type SpecRefusal = {
  readonly problems: string[];
  readonly fields: FieldProblem[];
};

/** One agent, with the spec currently being edited. */
export function useAgent(agentId: string | null) {
  const tErrors = useTranslations("errors");

  const queryClient = useQueryClient();
  const t = useTranslations("agents");

  const { data, isLoading } = useQuery({
    queryKey: qk.agents.detail(agentId ?? ""),
    queryFn: () => apiClient.get<AgentDetail>(`/agents/${agentId}`),
    enabled: !!agentId,
  });

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.agents.all() }),
    [queryClient],
  );

  // Publishing (and a rollback, which is a publish) repoints the default
  // environment server-side, and the environments cache is not under
  // `qk.agents` - without this the panel keeps naming the pin the publish
  // just moved, right after a dialog said it would move.
  const invalidateEnvironments = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.environments.list(agentId ?? "") }),
    [queryClient, agentId],
  );

  const saveDraft = useMutation({
    mutationFn: (spec: AgentSpec) => apiClient.put<Agent>(`/agents/${agentId}/draft`, { spec }),
    onSuccess: invalidate,
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  /**
   * Check the draft without publishing.
   *
   * Returns the problems rather than throwing: a rejected draft is a normal
   * state to be in while editing.
   *
   * Both halves of the refusal, because a capability's configuration is a
   * generated form and the rest of a spec is not. `problems` is the list the
   * page shows; `fields` is the subset that names an input, which the Builder
   * marks on the capability card that owns it - a `default_top_k` of 999 used
   * to arrive as one sentence about the capability, leaving the reader to find
   * which of its boxes was wrong (#882).
   */
  const validate = useCallback(async (): Promise<SpecRefusal> => {
    try {
      await apiClient.post<void>(`/agents/${agentId}/validate`, {});
      return { problems: [], fields: [] };
    } catch (error) {
      // This read used to be `error.details`, a property `ApiError` has never
      // had, so the list the backend goes out of its way to report in full was
      // always thrown away and replaced with one line. `problemList` reads the
      // envelope; the fallback is for the failures that are not a verdict on
      // the spec at all - a refused permission, a dropped connection.
      const problems = problemList(error);
      if (problems === null) return { problems: [getErrorMessage(error, tErrors)], fields: [] };
      return { problems, fields: fieldProblems(error) };
    }
  }, [agentId, tErrors]);

  const publish = useMutation({
    mutationFn: (note: string | null) =>
      apiClient.post<{ version: number }>(`/agents/${agentId}/publish`, { note }),
    onSuccess: async (version) => {
      await invalidate();
      await invalidateEnvironments();
      toast.success(t("publishedVersion", { version: version.version }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const rollback = useMutation({
    mutationFn: (versionId: string) =>
      apiClient.post<AgentVersion>(`/agents/${agentId}/rollback`, { version_id: versionId }),
    onSuccess: async (version) => {
      await invalidate();
      await invalidateEnvironments();
      // Rolling back publishes a *new* version rather than moving a pointer
      // backwards, so run history keeps telling the truth about what was live.
      toast.success(t("rolledBack", { version: version.version }));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
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
      toast.success(t("avatarUpdated"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  /**
   * Choose the colour of the agent's fallback avatar, or null for auto. A
   * column like the picture, not the spec, for the same reason `setAvatar` is.
   */
  const setColor = useMutation({
    mutationFn: (color: number | null) =>
      apiClient.patch<Agent>(`/agents/${agentId}/avatar-color`, { color }),
    onSuccess: async () => {
      await invalidate();
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return { agent: data, isLoading, saveDraft, validate, publish, rollback, setAvatar, setColor };
}

/** What the history card shows at once - a page a reader can take in. */
export const VERSIONS_PAGE_SIZE = 10;

/**
 * One page of an agent's publication history, newest first.
 *
 * `total` is every version rather than the length of this page, so a pager can
 * say how much history there is - and a caller that needs *every* version rather
 * than a page of them uses `useAllAgentVersions` below, which is what the
 * pickers do.
 */
export function useAgentVersions(
  agentId: string | null,
  options?: { skip?: number; limit?: number },
) {
  const skip = options?.skip ?? 0;
  const limit = options?.limit ?? VERSIONS_PAGE_SIZE;
  const { data, isLoading } = useQuery({
    queryKey: qk.agents.versions(agentId ?? "", skip, limit),
    queryFn: () =>
      apiClient.get<AgentVersionList>(`/agents/${agentId}/versions`, {
        params: { skip: String(skip), limit: String(limit) },
      }),
    enabled: !!agentId,
    // The page being read stays on screen while the next one loads, so paging a
    // history does not blank the card it is in.
    placeholderData: keepPreviousData,
  });
  return { versions: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/** The largest page the versions route will answer (`limit: le=100`). */
const VERSIONS_MAX_PAGE = 100;

/**
 * Every version an agent has, newest first, however many pages that takes.
 *
 * What the pickers need, and what one capped request cannot give them. This used
 * to be `useAgentVersions` with its default limit: an agent published more than
 * fifty times offered its newest fifty and silently hid the rest, so the version
 * an environment is pinned to could be missing from the environment picker, a
 * pinned delegate from the delegate picker, and the row somebody clicked on a
 * later page of the history from the comparison dropdown - which renders a
 * `<Select>` with no matching option as a blank trigger.
 *
 * Paged rather than raised to one large request, because `total` is the only
 * honest bound: the route caps `limit` at a hundred, so an agent with three
 * hundred publications is three requests and any cap here would be the same bug
 * at a higher number.
 */
export function useAllAgentVersions(agentId: string | null) {
  const { data, isLoading } = useQuery({
    queryKey: qk.agents.allVersions(agentId ?? ""),
    queryFn: async () => {
      const first = await apiClient.get<AgentVersionList>(`/agents/${agentId}/versions`, {
        params: { skip: "0", limit: String(VERSIONS_MAX_PAGE) },
      });
      const items = [...first.items];
      while (items.length < first.total && items.length > 0) {
        const next = await apiClient.get<AgentVersionList>(`/agents/${agentId}/versions`, {
          params: { skip: String(items.length), limit: String(VERSIONS_MAX_PAGE) },
        });
        // A page that answers nothing ends the walk rather than looping: a
        // publication deleted between two requests makes `total` larger than what
        // is left to read, and a `while` trusting the count alone would spin.
        if (next.items.length === 0) break;
        items.push(...next.items);
      }
      return { items, total: first.total };
    },
    enabled: !!agentId,
    placeholderData: keepPreviousData,
  });
  return { versions: data?.items ?? [], total: data?.total ?? 0, isLoading };
}

/**
 * The delegation tree under an agent's draft - what the map draws recursively.
 *
 * Fetched only while something shows it (`enabled`), because the walk resolves
 * and access-checks every pinned version server-side; the map dialog is the one
 * caller and it opens rarely. Saving the draft invalidates `qk.agents.all()`,
 * which this key sits under, so a re-pinned delegate is re-walked without
 * anything here knowing why.
 */
export function useDelegationTree(agentId: string | null, { enabled = true } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: qk.agents.delegationTree(agentId ?? ""),
    queryFn: () => apiClient.get<DelegationTree>(`/agents/${agentId}/delegation-tree`),
    enabled: enabled && !!agentId,
  });
  return { tree: data ?? null, isLoading, error };
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
