"use client";

import { useQuery } from "@tanstack/react-query";
import { getTableAssignees } from "@/lib/tables-api";
import { qk } from "@/lib/query-keys";

import { useMembers } from "./use-members";
import { useAgents } from "./use-agents";
import { useOrgStore } from "@/stores/org-store";
import type { RecordSource } from "@/types/tables";

export interface PrincipalOption extends RecordSource {
  detail?: string;
  archived?: boolean;
}

/** Reuses the console's tenant-scoped, permission-filtered directories. */
export function useTablePrincipals(kind: "user" | "agent", enabled = true) {
  const orgId = useOrgStore((state) => state.activeOrgId);
  const people = useMembers(kind === "user" && enabled ? (orgId ?? "") : "");
  const agents = useAgents({
    includeArchived: true,
    enabled: enabled && kind === "agent" && orgId !== null,
  });
  const items: PrincipalOption[] =
    kind === "user"
      ? people.members.map((member) => ({
          kind: "user",
          id: member.user_id,
          name: member.full_name || member.email,
          detail: member.email,
        }))
      : agents.agents.map((agent) => ({
          kind: "agent",
          archived: agent.status === "archived",
          id: agent.id,
          name: agent.name,
          detail: `@${agent.slug}`,
          slug: agent.slug,
          has_avatar: agent.has_avatar,
          avatar_color: agent.avatar_color,
        }));
  return {
    items,
    isLoading: kind === "user" ? people.isLoading : agents.isLoading,
    error: kind === "user" ? people.error : agents.error,
  };
}

export function useTableAssignees(tableId: string) {
  return useQuery({
    queryKey: qk.tables.assignees(tableId),
    queryFn: () => getTableAssignees(tableId),
    staleTime: 0,
  });
}
