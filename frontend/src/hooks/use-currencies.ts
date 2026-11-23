"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { currencyApi } from "@/lib/currency-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores/org-store";

export function useCurrencies() {
  const org = useOrgStore((state) => state.activeOrgId);
  return useQuery({
    queryKey: qk.currencies.current(org),
    queryFn: () => currencyApi.current(org!),
    enabled: org !== null,
  });
}

export function useOrganizationCurrency(org: string) {
  const client = useQueryClient();
  const context = useQuery({
    queryKey: qk.currencies.organization(org),
    queryFn: () => currencyApi.organization(org),
  });
  const save = useMutation({
    mutationFn: (currency: string | null) => currencyApi.setOrganization(org, currency),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.currencies.all() }),
        client.invalidateQueries({ queryKey: qk.organizations.list() }),
      ]);
    },
  });
  return { context, save };
}
