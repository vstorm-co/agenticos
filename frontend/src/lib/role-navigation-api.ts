import { apiClient } from "@/lib/api-client";
import type { RoleNavigationPolicy, UpdateRoleNavigation } from "@/types/role-navigation";

export function getRoleNavigation(organizationId: string, signal: AbortSignal) {
  return apiClient.get<RoleNavigationPolicy>("/roles/navigation", {
    headers: { "X-Organization-Id": organizationId },
    signal,
  });
}

export function updateRoleNavigation({ organizationId, role, hiddenItems }: UpdateRoleNavigation) {
  return apiClient.patch<RoleNavigationPolicy>(
    `/roles/navigation/${role}`,
    { hidden_items: hiddenItems },
    { headers: { "X-Organization-Id": organizationId } },
  );
}
