"use client";

import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  previewMemberStart,
  readOnboarding,
  saveOnboarding,
  prepareStarter,
  type StartUpdate,
} from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";

/** Readiness is live; a saved preference can never substitute for access or a real result. */
export function useStart(enabled = true) {
  const user = useAuthStore((s) => s.user?.id);
  const org = useOrgStore((s) => s.activeOrgId);
  const client = useQueryClient();
  const key = qk.onboarding.state(user ?? "", org ?? "");
  const state = useQuery({
    queryKey: key,
    queryFn: readOnboarding,
    enabled: enabled && !!user && !!org,
    staleTime: 10_000,
    // Mounting the prefetched checklist must keep an error available for Retry.
    retryOnMount: false,
    refetchOnWindowFocus: "always",
  });
  const snoozedUntil = state.data?.snoozed_until;
  const serverTime = state.data?.server_time;
  const { refetch, dataUpdatedAt } = state;
  useEffect(() => {
    if (!enabled || !snoozedUntil) return;
    // Measure against the response clock; local clock skew must not cause a retry loop.
    const remaining = Date.parse(snoozedUntil) - (serverTime ? Date.parse(serverTime) : Date.now());
    const timer = window.setTimeout(
      () => void refetch(),
      Math.min(86_400_000, Math.max(60_000, remaining)),
    );
    return () => window.clearTimeout(timer);
  }, [enabled, snoozedUntil, serverTime, refetch, dataUpdatedAt]);
  const save = useMutation({
    mutationKey: [...key, "save"],
    mutationFn: async (data: StartUpdate) => ({ key, data: await saveOnboarding(data) }),
    onSuccess: (saved) => client.setQueryData(saved.key, saved.data),
  });
  const prepare = useMutation({
    mutationKey: [...key, "prepare"],
    mutationFn: async (modelId: string) => ({ key, agent: await prepareStarter(modelId) }),
    onSuccess: async (prepared) => {
      await client.invalidateQueries({ queryKey: qk.agents.all() });
      await client.invalidateQueries({ queryKey: prepared.key });
    },
  });
  return { ...state, save, prepare, waitingForScope: !user || !org };
}

/** A manager's read-only preview is scoped to the active organization and target person. */
export function useMemberStartPreview(userId: string) {
  const org = useOrgStore((s) => s.activeOrgId);
  return useQuery({
    queryKey: qk.onboarding.preview(org ?? "", userId),
    queryFn: () => previewMemberStart(userId),
    enabled: !!org && !!userId,
  });
}
