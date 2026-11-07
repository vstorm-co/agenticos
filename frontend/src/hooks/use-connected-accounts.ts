"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { rememberMcpOAuthReturn } from "@/lib/mcp-oauth";
import { qk } from "@/lib/query-keys";
import type { ConnectedAccountList } from "@/types/mirage";

export type IntegrationProvider = "google" | "microsoft" | "slack" | "imap" | "odoo";
export interface AccountConnectOptions {
  label?: string;
  provider: IntegrationProvider;
  products: string[];
  write: boolean;
}

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
 * One owner's named provider accounts, shared by native tools and their other surfaces.
 *
 * Connecting leaves the page for the consent screen and comes back to
 * `returnTo`, where `useMcpOAuthOutcome` says how it went - the callback is the
 * one MCP consents use. `enabled` lets a caller that may not list the
 * organization's accounts not ask for them.
 */
export function useConnectedAccounts(
  owner: AccountOwner,
  {
    enabled = true,
    provider = "google",
  }: { enabled?: boolean; provider?: IntegrationProvider } = {},
) {
  const t = useTranslations("errors");
  const queryClient = useQueryClient();
  const accounts = useQuery({
    queryKey: provider === "google" ? KEY[owner]() : [...KEY[owner](), provider],
    queryFn: () =>
      apiClient.get<ConnectedAccountList>(
        provider === "google" ? PREFIX[owner] : `${PREFIX[owner]}?provider=${provider}`,
      ),
    enabled,
  });
  const connect = useMutation({
    mutationFn: async ({
      returnTo,
      options,
    }: {
      returnTo: string;
      options?: AccountConnectOptions;
    }) => {
      const { authorization_url } = await apiClient.post<{ authorization_url: string }>(
        `${PREFIX[owner]}/oauth/start`,
        options,
      );
      rememberMcpOAuthReturn(returnTo);
      window.location.assign(authorization_url);
    },
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  const connectOdoo = useMutation({
    mutationFn: (data: {
      credential: { origin: string; database: string; api_key: string };
      label: string;
      write: boolean;
    }) => apiClient.post(`${PREFIX[owner]}/odoo`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY[owner]() }),
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  const connectImap = useMutation({
    mutationFn: (data: {
      credential: {
        host: string;
        port: number;
        username: string;
        password: string;
        folder: string;
      };
      label: string;
    }) => apiClient.post(`${PREFIX[owner]}/imap`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY[owner]() }),
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  const connectApplication = useMutation({
    mutationFn: (data: {
      provider: IntegrationProvider;
      secret_id: string;
      subject: string | null;
      products: string[];
      write: boolean;
      label: string;
    }) => apiClient.post(`${PREFIX[owner]}/application`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY[owner]() }),
    onError: (cause) => toast.error(getErrorMessage(cause, t)),
  });
  const connectToken = useMutation({
    mutationFn: (data: { token: string; label: string }) =>
      apiClient.post(`${PREFIX[owner]}/slack/token`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: KEY[owner]() }),
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
    connect: (returnTo: string, options?: AccountConnectOptions) =>
      connect.mutate({ returnTo, options }),
    isConnecting: connect.isPending,
    connectToken,
    connectApplication,
    connectImap,
    connectOdoo,
    disconnect: (id: string) => disconnect.mutate(id),
  };
}
