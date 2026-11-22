"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import {
  cancelSubscriptionSignIn,
  completeSubscriptionSignIn,
  disconnectSubscriptionAccount,
  listSubscriptionAccounts,
  selectSubscriptionAccountModel,
  listSubscriptionAccountModels,
  subscriptionBelongsTo,
  readSubscriptionUsage,
  type SubscriptionProvider,
  startSubscriptionSignIn,
  subscriptionSignInStatus,
} from "@/lib/subscription-accounts-api";

import { subscriptionModelId } from "@/lib/subscription-model-id";

interface Scope {
  tenant: string | null;
  user: string | undefined;
}

/** The chosen vendor's actual account catalogs, including models made by other vendors. */
export function useSubscriptionModels(provider: SubscriptionProvider, accountName?: string) {
  const actions = useSubscriptionAccounts();
  const accounts = (actions.accounts.data?.items ?? []).filter(
    (account) =>
      subscriptionBelongsTo(account, provider) &&
      !account.disabled &&
      !account.unavailable &&
      account.name === accountName,
  );
  const listings = useQueries({
    queries: accounts.map((account) => ({
      queryKey: qk.subscriptionAccounts.models(actions.scope, account.name),
      queryFn: () => listSubscriptionAccountModels(account.name),
      staleTime: 0,
      retry: false,
    })),
  });
  return {
    models: [
      ...new Set(listings.flatMap((listing) => listing.data ?? []).map(subscriptionModelId)),
    ].map((id) => ({
      id,
      name: id,
    })),
    loading: actions.accounts.isLoading || listings.some((listing) => listing.isFetching),
    error: actions.accounts.error ?? listings.find((listing) => listing.error)?.error,
    refetch: () =>
      Promise.all([actions.accounts.refetch(), ...listings.map((listing) => listing.refetch())]),
  };
}

/** The signed-in person's own subscription accounts in the current organization. */
export function useSubscriptionAccounts({ enabled = true }: { enabled?: boolean } = {}) {
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
    enabled: enabled && !!tenant && !!user,
    refetchInterval: 60_000,
  });
  return {
    accounts,
    selectModel: useMutation({
      mutationFn: ({ name, model }: { name: string; model: string }) =>
        selectSubscriptionAccountModel(name, model),
    }),
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
    isCurrentScope: () => guard(tenant) && useAuthStore.getState().user?.id === user,
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

/** Poll only while a view of this account’s limits is mounted. */
export function useSubscriptionUsage(name: string, enabled: boolean, provider: string) {
  const interval = provider === "claude" || provider === "anthropic" ? 300_000 : 60_000;
  const actions = useSubscriptionAccounts();
  return useQuery({
    queryKey: qk.subscriptionAccounts.usage(actions.scope, name),
    queryFn: () => readSubscriptionUsage(name),
    enabled: actions.ready && enabled,
    staleTime: interval,
    refetchInterval: interval,
    retry: false,
  });
}
