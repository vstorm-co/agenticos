"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type { ConnectedAppList, OAuthConsentAnswer, OAuthConsentRequest } from "@/types/mcp-oauth";
import type { Permission } from "@/types/permissions";

/**
 * One MCP client's request for access, in the active organization, and the two
 * answers to it. Both answers resolve with where to send the browser next - the
 * client's own redirect, carrying a code or `access_denied`.
 */
export function useConsentRequest(requestId: string) {
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "current";
  const request = useQuery({
    queryKey: qk.mcpOauth.request(orgId, requestId),
    queryFn: () => apiClient.get<OAuthConsentRequest>(`/mcp-oauth/requests/${requestId}`),
    retry: false,
  });
  const approve = useMutation({
    mutationFn: (scopes: Permission[]) =>
      apiClient.post<OAuthConsentAnswer>(`/mcp-oauth/requests/${requestId}/approve`, { scopes }),
  });
  const deny = useMutation({
    mutationFn: () => apiClient.post<OAuthConsentAnswer>(`/mcp-oauth/requests/${requestId}/deny`),
  });
  return {
    request: request.data ?? null,
    isLoading: request.isLoading,
    error: request.error,
    approve,
    deny,
  };
}

/** The applications connected as the caller - everybody's with `api_keys:manage`. */
export function useConnectedApps() {
  const t = useTranslations("mcpOauth");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "current";
  const list = useQuery({
    queryKey: qk.mcpOauth.grants(orgId),
    queryFn: () => apiClient.get<ConnectedAppList>("/mcp-oauth/grants"),
  });
  const disconnect = useMutation({
    mutationFn: (grantId: string) => apiClient.delete<void>(`/mcp-oauth/grants/${grantId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.mcpOauth.grants(orgId) });
      toast.success(t("disconnected"));
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, tErrors)),
  });
  return {
    apps: list.data?.items ?? [],
    isLoading: list.isLoading,
    error: list.error,
    refetch: list.refetch,
    disconnect,
  };
}
