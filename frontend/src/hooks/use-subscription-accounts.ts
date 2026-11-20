"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import {
  cancelSubscriptionSignIn,
  completeSubscriptionSignIn,
  disconnectSubscriptionAccount,
  listSubscriptionAccounts,
  startSubscriptionSignIn,
  subscriptionSignInStatus,
} from "@/lib/subscription-accounts-api";

interface Scope {
  tenant: string | null;
  user: string | undefined;
}

/** The signed-in person's own subscription accounts in the current organization. */
export function useSubscriptionAccounts() {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  const guard = useTenantGuard();
  const client = useQueryClient();
  const scope = `${tenant ?? ""}:${user ?? ""}`;
  // The audience a mutation started under, not the latest render's: switching
  // organizations mid-sign-in must not refresh the other one's list.
  const lifecycle = {
    onMutate: (): Scope => ({ tenant, user }),
    onSettled: (_data: unknown, _error: unknown, _variables: unknown, started?: Scope) => {
      if (started && guard(started.tenant) && useAuthStore.getState().user?.id === started.user)
        void client.invalidateQueries({
          queryKey: qk.subscriptionAccounts.mine(`${started.tenant ?? ""}:${started.user ?? ""}`),
        });
    },
  };
  const accounts = useQuery({
    queryKey: qk.subscriptionAccounts.mine(scope),
    queryFn: listSubscriptionAccounts,
    enabled: !!tenant && !!user,
  });
  return {
    accounts,
    start: useMutation({ mutationFn: startSubscriptionSignIn }),
    complete: useMutation({
      mutationFn: ({ state, redirectUrl }: { state: string; redirectUrl: string }) =>
        completeSubscriptionSignIn(state, redirectUrl),
      ...lifecycle,
    }),
    cancel: useMutation({ mutationFn: cancelSubscriptionSignIn }),
    disconnect: useMutation({ mutationFn: disconnectSubscriptionAccount, ...lifecycle }),
    refresh: () => client.invalidateQueries({ queryKey: qk.subscriptionAccounts.mine(scope) }),
    scope,
    ready: !!tenant && !!user,
  };
}

/** Polls one sign-in until the provider approves or refuses it. */
export function useSubscriptionSignInStatus(scope: string, state: string | null) {
  return useQuery({
    queryKey: qk.subscriptionAccounts.signIn(scope, state ?? ""),
    queryFn: () => subscriptionSignInStatus(state ?? ""),
    enabled: state !== null,
    refetchInterval: (query) =>
      query.state.error || (query.state.data && query.state.data.status !== "wait") ? false : 3000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}
