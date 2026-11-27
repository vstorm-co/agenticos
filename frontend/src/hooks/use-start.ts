"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  previewMemberStart,
  readOnboarding,
  saveOnboarding,
  prepareStarter,
  type StartUpdate,
  type StartScope,
  type StartScopeUpdate,
  saveOnboardingScope,
} from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import { pendingSharedStart } from "@/lib/onboarding/scopes";

/** Readiness is live; a saved preference can never substitute for access or a real result. */
export function useStart(enabled = true) {
  const errors = useTranslations("errors");
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
    refetchInterval: (query) =>
      query.state.data && pendingSharedStart(query.state.data) ? 10_000 : false,
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
  type Owner = { userId: string | undefined; organizationId: string | null };
  const owns = (owner: Owner): boolean =>
    !!owner.userId &&
    !!owner.organizationId &&
    useAuthStore.getState().user?.id === owner.userId &&
    useOrgStore.getState().activeOrgId === owner.organizationId;
  const save = useMutation({
    mutationKey: [...key, "save"],
    mutationFn: async (write: Owner & { data: StartUpdate }) => {
      const { userId, organizationId } = write;
      if (!userId || !organizationId || !owns(write)) throw new Error(errors("sessionExpired"));
      return {
        userId,
        organizationId,
        key: qk.onboarding.state(userId, organizationId),
        data: await saveOnboarding(write.data, organizationId),
      };
    },
    onSuccess: (saved) => {
      if (owns(saved) || client.getQueryState(saved.key))
        client.setQueryData(saved.key, saved.data);
    },
  });
  type ScopeRequest = { scope: StartScope; data: StartScopeUpdate };
  const saveScope = useMutation({
    mutationKey: [...key, "scope"],
    scope: { id: `onboarding-scope:${user}:${org}` },
    mutationFn: async (write: Owner & ScopeRequest) => {
      const { userId, organizationId } = write;
      if (!userId || !organizationId || !owns(write)) throw new Error(errors("sessionExpired"));
      return {
        userId,
        organizationId,
        key: qk.onboarding.state(userId, organizationId),
        data: await saveOnboardingScope(write.scope, write.data, organizationId),
      };
    },
    onSuccess: async (saved) => {
      if (owns(saved) || client.getQueryState(saved.key))
        client.setQueryData(saved.key, saved.data);
      if (owns(saved)) await client.invalidateQueries({ queryKey: qk.onboarding.all() });
    },
    onError: (_error, write) => {
      if (owns(write))
        return client.invalidateQueries({
          queryKey: qk.onboarding.state(write.userId ?? "", write.organizationId ?? ""),
        });
    },
  });
  const prepare = useMutation({
    mutationKey: [...key, "prepare"],
    mutationFn: async (write: Owner & { modelId: string }) => {
      const { userId, organizationId } = write;
      if (!userId || !organizationId || !owns(write)) throw new Error(errors("sessionExpired"));
      return {
        userId,
        organizationId,
        key: qk.onboarding.state(userId, organizationId),
        agent: await prepareStarter(write.modelId, organizationId),
      };
    },
    onSuccess: async (prepared) => {
      if (owns(prepared)) await client.invalidateQueries({ queryKey: qk.agents.all() });
      if (owns(prepared) || client.getQueryState(prepared.key))
        await client.invalidateQueries({ queryKey: prepared.key });
    },
  });
  // Mutation observers adopt new options after a scope change; variables must retain the caller's owner.
  return {
    ...state,
    waitingForScope: !user || !org,
    save: {
      ...save,
      mutate: (data: StartUpdate, options?: Parameters<typeof save.mutate>[1]) =>
        save.mutate({ data, userId: user, organizationId: org }, options),
      mutateAsync: (data: StartUpdate, options?: Parameters<typeof save.mutateAsync>[1]) =>
        save.mutateAsync({ data, userId: user, organizationId: org }, options),
    },
    saveScope: {
      ...saveScope,
      mutate: (data: ScopeRequest, options?: Parameters<typeof saveScope.mutate>[1]) =>
        saveScope.mutate({ ...data, userId: user, organizationId: org }, options),
      mutateAsync: (data: ScopeRequest, options?: Parameters<typeof saveScope.mutateAsync>[1]) =>
        saveScope.mutateAsync({ ...data, userId: user, organizationId: org }, options),
    },
    prepare: {
      ...prepare,
      mutate: (modelId: string, options?: Parameters<typeof prepare.mutate>[1]) =>
        prepare.mutate({ modelId, userId: user, organizationId: org }, options),
      mutateAsync: (modelId: string, options?: Parameters<typeof prepare.mutateAsync>[1]) =>
        prepare.mutateAsync({ modelId, userId: user, organizationId: org }, options),
    },
  };
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
