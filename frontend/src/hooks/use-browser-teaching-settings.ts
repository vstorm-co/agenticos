"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  isTeachingAudienceCurrent,
  listBrowserTeachings,
  readTeachingPolicy,
  readTeachingPreference,
  readTeachingRun,
  readTeachingSkills,
  updateTeachingPolicy,
  updateTeachingPreference,
} from "@/lib/browser-teaching-api";
import { isTeachingId } from "@/lib/browser-teaching-review";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { TeachingToggle } from "@/types/browser-teaching";

export function useTeachingAudience() {
  const actor = useAuthStore((state) => state.user?.id);
  const organization = useOrgStore((state) => state.activeOrgId);
  return { actor, organization };
}
export function useTeachingPolicy(enabled = true) {
  const audience = useTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserTeaching.policy(audience.actor, audience.organization);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => readTeachingPolicy(audience, signal),
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
    mutationFn: (body: TeachingToggle) => updateTeachingPolicy(audience, body),
    onMutate: () => client.cancelQueries({ queryKey }),
    onSuccess: (data) => {
      if (isTeachingAudienceCurrent(audience)) client.setQueryData(queryKey, data);
    },
    onSettled: () => {
      if (isTeachingAudienceCurrent(audience))
        void client.invalidateQueries({
          queryKey: qk.browserTeaching.all(audience.actor, audience.organization),
        });
    },
  });
  return { ...query, data: enabled && !query.error ? query.data : undefined, update };
}
export function useTeachingPreference(agentId: string | null, enabled = true) {
  const audience = useTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserTeaching.preference(
    audience.actor,
    audience.organization,
    agentId ?? "",
  );
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => readTeachingPreference(audience, agentId!, signal),
    enabled:
      enabled && !!audience.actor && !!audience.organization && !!agentId && isTeachingId(agentId),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: "always",
  });
  const update = useMutation({
    mutationKey: [...queryKey, "update"],
    retry: false,
    gcTime: 0,
    mutationFn: (body: TeachingToggle) => updateTeachingPreference(audience, agentId!, body),
    onMutate: () => client.cancelQueries({ queryKey }),
    onSuccess: (data) => {
      if (isTeachingAudienceCurrent(audience) && data.agent_id === agentId)
        client.setQueryData(queryKey, data);
    },
    onSettled: () => {
      if (isTeachingAudienceCurrent(audience)) void client.invalidateQueries({ queryKey });
    },
  });
  return {
    ...query,
    data: enabled && !query.error && query.data?.agent_id === agentId ? query.data : undefined,
    update,
  };
}
export function useTeachingRun(runId: string, enabled: boolean) {
  const audience = useTeachingAudience();
  const query = useQuery({
    queryKey: qk.browserTeaching.run(audience.actor, audience.organization, runId),
    queryFn: ({ signal }) => readTeachingRun(audience, runId, signal),
    enabled: enabled && !!audience.actor && !!audience.organization && isTeachingId(runId),
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
export function useTeachingSkills(enabled: boolean) {
  const audience = useTeachingAudience();
  const query = useInfiniteQuery({
    queryKey: qk.browserTeaching.skills(audience.actor, audience.organization),
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) => readTeachingSkills(audience, pageParam, signal),
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

export function useTeachingList() {
  const audience = useTeachingAudience();
  const client = useQueryClient();
  const queryKey = qk.browserTeaching.list(audience.actor, audience.organization);
  const query = useInfiniteQuery({
    queryKey,
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => listBrowserTeachings(audience, pageParam, signal),
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
