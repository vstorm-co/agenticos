"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { qk } from "@/lib/query-keys";
import { readToolConsents, revokeToolConsent } from "@/lib/tool-consents-api";

export function useToolConsents() {
  const org = useOrgStore((state) => state.activeOrgId);
  const user = useAuthStore((state) => state.user?.id);
  const client = useQueryClient();
  const key = qk.runs.consents(org, user);
  const query = useQuery({
    queryKey: key,
    queryFn: readToolConsents,
    enabled: Boolean(org && user),
    staleTime: 0,
  });
  const revoke = useMutation({
    mutationFn: revokeToolConsent,
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  return { query, revoke };
}
