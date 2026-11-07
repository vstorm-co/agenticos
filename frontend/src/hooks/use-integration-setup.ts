"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { IntegrationProvider } from "@/hooks/use-connected-accounts";
import type { StorableSecretKind } from "@/types/secrets";

interface IntegrationProduct {
  id: string;
  name: string;
  read_scopes: string[];
  write_scopes: string[];
  application_supported: boolean;
  application_read_scopes: string[];
  application_write_scopes: string[];
}
interface IntegrationSetup {
  provider: IntegrationProvider;
  identity_scopes: string[];
  redirect_uri: string;
  console_url: string;
  secret_kind: StorableSecretKind;
  products: IntegrationProduct[];
  enable_apis_command: string | null;
  manifest_url: string | null;
}

export function useIntegrationSetup(provider: IntegrationProvider, write = false) {
  return useQuery({
    queryKey: [...qk.connectedAccounts.setup(provider), write],
    queryFn: () =>
      apiClient.get<IntegrationSetup>(`/me/connected-accounts/setup/${provider}?write=${write}`),
  });
}
