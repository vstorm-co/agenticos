"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { BindingRequest } from "@/types/channels";

interface BindingRequestList {
  items: BindingRequest[];
  total: number;
}

/**
 * What one agent is waiting on an administrator for: a binding to a public line,
 * a change of its environment, or lifting a pause. Per-resource, so an agent's
 * publisher reads it without `channels:manage`.
 */
export function useBindingRequests(agentId: string | null) {
  return useQuery({
    queryKey: qk.exposures.requests(agentId ?? ""),
    queryFn: async () =>
      (await apiClient.get<BindingRequestList>(`/agents/${agentId}/binding-requests`)).items,
    enabled: agentId !== null,
  });
}

/**
 * The organization's requests to change a public line, and the two ways to answer one.
 *
 * Needs `channels:manage`, so callers say whether they hold it and nothing is
 * fetched otherwise. An approval applies the change, so it refreshes the bindings
 * and the bots as well as the list.
 */
export function useChannelBindingRequests(enabled: boolean) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("pages.channels");
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: qk.channelBots.bindingRequests(),
    queryFn: () => apiClient.get<BindingRequestList>("/channels/binding-requests"),
    enabled,
  });

  const settled = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: qk.channelBots.bindingRequests() }),
      queryClient.invalidateQueries({ queryKey: qk.exposures.all() }),
      queryClient.invalidateQueries({ queryKey: qk.channelBots.list() }),
    ]);
  };

  const approve = useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<BindingRequest>(`/channels/binding-requests/${requestId}/approve`, {}),
    onSuccess: async () => {
      await settled();
      toast.success(t("bindingApproved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  const decline = useMutation({
    mutationFn: (requestId: string) =>
      apiClient.post<BindingRequest>(`/channels/binding-requests/${requestId}/decline`, {}),
    onSuccess: async () => {
      await settled();
      toast.success(t("bindingDeclined"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    requests: data?.items ?? [],
    isLoading,
    approve,
    decline,
  };
}
