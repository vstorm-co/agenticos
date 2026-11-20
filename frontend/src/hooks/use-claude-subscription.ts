"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import {
  cancelClaudeSubscriptionLogin,
  claudeSubscriptionPollInterval,
  disconnectClaudeSubscription,
  readClaudeSubscription,
  startClaudeSubscriptionLogin,
  submitClaudeSubscriptionCode,
} from "@/lib/personal-subscriptions-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";

type Action = "start" | "submit" | "cancel" | "disconnect";

/**
 * A private connection, keyed by both its person and organization.
 *
 * Codes go straight to the request, never into React Query's retained mutation
 * variables. Cancel, unmount and a scope change invalidate pending responses.
 * Status checks stop once sign-in ends, so the native client is not repeatedly
 * asked to refresh its credentials while an agent is using them.
 */
export function useClaudeSubscription({ enabled }: { enabled: boolean }) {
  const tenant = useTenantId();
  const person = useAuthStore((state) => state.user);
  const user = person?.id;
  const guard = useTenantGuard();
  const client = useQueryClient();
  const scope = `${tenant ?? ""}:${user ?? ""}`;
  const key = useMemo(() => qk.personalSubscriptions.claude(scope), [scope]);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const [working, setWorking] = useState<{ scope: string; action: Action } | null>(null);
  const [failure, setFailure] = useState<{ scope: string; at: number } | null>(null);
  const ready = enabled && !!tenant && !!user && !person?.impersonation;
  const action = working?.scope === scope ? working.action : null;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
      controller.current?.abort();
      controller.current = null;
      setWorking(null);
      setFailure(null);
    };
  }, [scope]);

  const currentScope = useCallback(() => {
    const current = useAuthStore.getState().user;
    return mounted.current && guard(tenant) && current?.id === user && !current?.impersonation;
  }, [guard, tenant, user]);

  const invalidateModels = useCallback(
    (next: ClaudeSubscriptionStatus) => {
      const previous = client.getQueryData<ClaudeSubscriptionStatus>(key);
      if (currentScope() && previous?.connected !== next.connected)
        void client.invalidateQueries({ queryKey: qk.providers.modelProfiles() });
    },
    [client, currentScope, key],
  );

  const status = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const next = await readClaudeSubscription(signal);
      if (!signal.aborted) invalidateModels(next);
      return next;
    },
    enabled: ready && action === null,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (query) =>
      action === null && query.state.error === null
        ? claudeSubscriptionPollInterval(query.state.data)
        : false,
  });

  const run = useCallback(
    async (name: Action, request: (signal: AbortSignal) => Promise<ClaudeSubscriptionStatus>) => {
      if (!ready || !currentScope()) return;
      const started = ++generation.current;
      controller.current?.abort();
      const pending = new AbortController();
      controller.current = pending;
      setFailure(null);
      setWorking({ scope, action: name });
      await client.cancelQueries({ queryKey: key });
      try {
        if (generation.current !== started || !currentScope()) return;
        const next = await request(pending.signal);
        if (generation.current !== started || !currentScope()) return;
        invalidateModels(next);
        client.setQueryData(key, next);
      } catch {
        if (generation.current === started && currentScope()) setFailure({ scope, at: Date.now() });
      } finally {
        if (generation.current === started && currentScope()) {
          controller.current = null;
          setWorking(null);
        }
      }
    },
    [client, currentScope, invalidateModels, key, ready, scope],
  );

  return {
    status,
    scope,
    ready,
    action,
    failed: failure?.scope === scope && failure.at >= status.dataUpdatedAt,
    start: () => run("start", startClaudeSubscriptionLogin),
    submit: (loginId: string, code: string) =>
      run("submit", (signal) => submitClaudeSubscriptionCode(loginId, code, signal)),
    cancel: (loginId: string) =>
      run("cancel", (signal) => cancelClaudeSubscriptionLogin(loginId, signal)),
    disconnect: () => run("disconnect", disconnectClaudeSubscription),
  };
}
