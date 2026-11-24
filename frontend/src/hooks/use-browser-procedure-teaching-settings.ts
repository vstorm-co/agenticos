"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  isBrowserProcedureTeachingAudienceCurrent,
  listBrowserProcedureTeachings,
  readBrowserProcedureTeachingPolicy,
  readBrowserProcedureTeachingPreference,
  readBrowserProcedureTeachingRun,
  readBrowserProcedureTeachingSkills,
  updateBrowserProcedureTeachingPolicy,
  updateBrowserProcedureTeachingPreference,
} from "@/lib/browser-procedure-teaching-api";
import { isBrowserProcedureTeachingId } from "@/lib/browser-procedure-teaching-review";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { BrowserProcedureTeachingToggle } from "@/types/browser-procedure-teaching";

export function useBrowserProcedureTeachingAudience() {
  const actor = useAuthStore((state) => state.user?.id);
  const organization = useOrgStore((state) => state.activeOrgId);
  return { actor, organization };
}
export function useBrowserProcedureTeachingPolicy(enabled = true) {
  const audience = useBrowserProcedureTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserProcedureTeaching.policy(audience.actor, audience.organization);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => readBrowserProcedureTeachingPolicy(audience, signal),
    enabled: enabled && !!audience.actor && !!audience.organization,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  const update = useMutation({
    mutationKey: [...queryKey, "update"],
    retry: false,
    gcTime: 0,
    mutationFn: (body: BrowserProcedureTeachingToggle) =>
      updateBrowserProcedureTeachingPolicy(audience, body),
    onMutate: () => client.cancelQueries({ queryKey }),
    onSuccess: (data) => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience)) client.setQueryData(queryKey, data);
    },
    onSettled: () => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserProcedureTeaching.all(audience.actor, audience.organization),
        });
    },
  });
  return { ...query, data: enabled && !query.error ? query.data : undefined, update };
}
export function useBrowserProcedureTeachingPreference(agentId: string | null, enabled = true) {
  const audience = useBrowserProcedureTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserProcedureTeaching.preference(
    audience.actor,
    audience.organization,
    agentId ?? "",
  );
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => readBrowserProcedureTeachingPreference(audience, agentId!, signal),
    enabled:
      enabled &&
      !!audience.actor &&
      !!audience.organization &&
      !!agentId &&
      isBrowserProcedureTeachingId(agentId),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  const update = useMutation({
    mutationKey: [...queryKey, "update"],
    retry: false,
    gcTime: 0,
    mutationFn: (body: BrowserProcedureTeachingToggle) =>
      updateBrowserProcedureTeachingPreference(audience, agentId!, body),
    onMutate: () => client.cancelQueries({ queryKey }),
    onSuccess: (data) => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience) && data.agent_id === agentId)
        client.setQueryData(queryKey, data);
    },
    onSettled: () => {
      if (isBrowserProcedureTeachingAudienceCurrent(audience))
        void client.invalidateQueries({ queryKey });
    },
  });
  return {
    ...query,
    data: enabled && !query.error && query.data?.agent_id === agentId ? query.data : undefined,
    update,
  };
}
export function useBrowserProcedureTeachingRun(runId: string, enabled: boolean) {
  const audience = useBrowserProcedureTeachingAudience();
  const query = useQuery({
    queryKey: qk.browserProcedureTeaching.run(audience.actor, audience.organization, runId),
    queryFn: ({ signal }) => readBrowserProcedureTeachingRun(audience, runId, signal),
    enabled:
      enabled && !!audience.actor && !!audience.organization && isBrowserProcedureTeachingId(runId),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  return {
    ...query,
    data: enabled && !query.error && query.data?.id === runId ? query.data : undefined,
  };
}
export function useBrowserProcedureTeachingSkills(enabled: boolean) {
  const audience = useBrowserProcedureTeachingAudience();
  const query = useInfiniteQuery({
    queryKey: qk.browserProcedureTeaching.skills(audience.actor, audience.organization),
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      readBrowserProcedureTeachingSkills(audience, pageParam, signal),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((sum, page) => sum + page.items.length, 0);
      return last.items.length && loaded < last.total ? loaded : undefined;
    },
    enabled: enabled && !!audience.actor && !!audience.organization,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  return { ...query, data: enabled && !query.error ? query.data : undefined };
}

export function useBrowserProcedureTeachingList() {
  const audience = useBrowserProcedureTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserProcedureTeaching.list(audience.actor, audience.organization);
  const query = useInfiniteQuery({
    queryKey,
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => listBrowserProcedureTeachings(audience, pageParam, signal),
    getNextPageParam: (last) => last.next_cursor,
    enabled: !!audience.actor && !!audience.organization,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  const restart = () => client.resetQueries({ queryKey, exact: true });
  return { ...query, data: !query.error ? query.data : undefined, restart };
}
