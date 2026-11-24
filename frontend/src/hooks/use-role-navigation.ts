"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getRoleNavigation, updateRoleNavigation } from "@/lib/role-navigation-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

export function useRoleNavigation(organizationId: string) {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  return useQuery({
    queryKey: qk.organizations.roleNavigation(organizationId),
    queryFn: ({ signal }) => getRoleNavigation(organizationId, signal),
    enabled: activeOrgId === organizationId,
  });
}

export function useUpdateRoleNavigation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateRoleNavigation,
    onSuccess: async (policy, { organizationId }) => {
      // A late reply must not repopulate the cache cleared by an organization switch.
      if (useOrgStore.getState().activeOrgId !== organizationId) return;
      queryClient.setQueryData(qk.organizations.roleNavigation(organizationId), policy);
      await queryClient.invalidateQueries({
        queryKey: qk.organizations.permissions(organizationId),
      });
    },
  });
}
