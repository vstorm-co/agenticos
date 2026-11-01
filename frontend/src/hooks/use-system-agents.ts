"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listSystemAgents,
  updateSystemAgent,
  type SystemAgent,
  type SystemAgentUpdate,
  type SystemRole,
} from "@/lib/system-agents-api";
import { qk } from "@/lib/query-keys";
import { useTenantId } from "@/hooks/use-organizations";

/**
 * The platform's background roles in the active organization, and a way to change
 * the one that has a profile of its own. Keyed on the organization: roles, models
 * and spend are per tenant.
 */
export function useSystemAgents(enabled: boolean) {
  const queryClient = useQueryClient();
  const tenantId = useTenantId();
  const key = qk.systemAgents.list(tenantId ?? "current");

  const query = useQuery<SystemAgent[]>({ queryKey: key, queryFn: listSystemAgents, enabled });
  const update = useMutation({
    mutationFn: ({ role, change }: { role: SystemRole; change: SystemAgentUpdate }) =>
      updateSystemAgent(role, change),
    onSuccess: (saved) =>
      queryClient.setQueryData<SystemAgent[]>(key, (roles) =>
        roles?.map((known) => (known.role === saved.role ? saved : known)),
      ),
  });
  return { roles: query.data, isLoading: query.isLoading, error: query.error, update };
}
