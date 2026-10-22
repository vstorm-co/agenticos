"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { rememberMcpOAuthReturn } from "@/lib/mcp-oauth";
import { qk } from "@/lib/query-keys";
import type { ConnectedAccountList } from "@/types/mirage";

export type AccountOwner = "personal" | "organization";

const PREFIX: Record<AccountOwner, string> = {
  personal: "/me/connected-accounts",
  organization: "/connected-accounts",
};

const KEY = {
  personal: qk.connectedAccounts.mine,
  organization: qk.connectedAccounts.organization,
};

/**
 * One owner's connected accounts: the Google sign-ins a virtual terminal's mount reads as.
 *
 * Connecting leaves the page for the consent screen and comes back to
 * `returnTo`, where `useMcpOAuthOutcome` says how it went - the callback is the
 * one MCP consents use. `enabled` lets a caller that may not list the
 * organization's accounts not ask for them.
 */
export function useConnectedAccounts(owner: AccountOwner, { enabled = true } = {}) {
  const t = useTranslations("errors");
  const queryClient = useQueryClient();
  const accounts = useQuery({
    queryKey: KEY[owner](),
    queryFn: () => apiClient.get<ConnectedAccountList>(PREFIX[owner]),
    enabled,
  });
  const connect = useMutation({
    mutationFn: async (returnTo: string) => {
      const { authorization_url } = await apiClient.post<{ authorization_url: string }>(
        `${PREFIX[owner]}/oauth/start`,
      );
      rememberMcpOAuthReturn(returnTo);
      window.location.assign(authorization_url);
    },
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  const disconnect = useMutation({
    mutationFn: (id: string) => apiClient.delete(`${PREFIX[owner]}/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY[owner]() }),
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  return {
    accounts: accounts.data?.items ?? [],
    isLoading: accounts.isLoading,
    error: accounts.error,
    connect: (returnTo: string) => connect.mutate(returnTo),
    isConnecting: connect.isPending,
    disconnect: (id: string) => disconnect.mutate(id),
  };
}
