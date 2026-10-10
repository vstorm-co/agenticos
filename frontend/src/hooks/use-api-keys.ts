"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import type {
  ApiKeyCreateInput,
  ApiKeyCreated,
  ApiKeyList,
  ApiKeyScopeCatalog,
} from "@/types/api-keys";

/**
 * The caller's organization API keys - or every key, with `api_keys:manage` -
 * and the two things done to them.
 *
 * `create` resolves with the key itself, which no other response carries: the
 * dialog that asked for it is the only place it can be shown, so the hook hands
 * it back rather than caching it anywhere.
 */
export function useApiKeys({ canCreate }: { canCreate: boolean }) {
  const t = useTranslations("apiKeys");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const orgId = useOrgStore((state) => state.activeOrgId) ?? "current";

  const list = useQuery({
    queryKey: qk.apiKeys.list(orgId),
    queryFn: () => apiClient.get<ApiKeyList>("/api-keys"),
  });
  const scopes = useQuery({
    queryKey: qk.apiKeys.scopes(orgId),
    queryFn: () => apiClient.get<ApiKeyScopeCatalog>("/api-keys/scopes"),
    enabled: canCreate,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: qk.apiKeys.all(orgId) });

  const create = useMutation({
    mutationFn: (input: ApiKeyCreateInput) => apiClient.post<ApiKeyCreated>("/api-keys", input),
    onSuccess: () => void refresh(),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/api-keys/${id}`),
    onSuccess: () => {
      void refresh();
      toast.success(t("revoked"));
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    keys: list.data?.items ?? [],
    isLoading: list.isLoading,
    error: list.error,
    refetch: list.refetch,
    catalog: scopes.data ?? null,
    create,
    revoke,
  };
}
