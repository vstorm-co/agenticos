"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import type { AgentResourceRef } from "@/lib/agent-spec";
import { qk } from "@/lib/query-keys";
import { useAddToAgentStore, useOrgStore } from "@/stores";
import { Perm, type MyPermissions } from "@/types/permissions";

/**
 * The toast that says a skill, a context file or a knowledge base was created,
 * offering to add it to an agent straight away (#2072).
 *
 * Something made and given to no agent does nothing, and the moment it is made
 * is when its author knows which agent it was for. Offered only to somebody
 * who may edit agents - an action that ends in a refusal is worse than none.
 * The permission is read from what `usePermissions` already cached for the
 * console, when the toast is shown, so a data hook does not start a query of
 * its own for it.
 */
export function useCreatedToast() {
  const t = useTranslations("agents");
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const open = useAddToAgentStore((state) => state.open);

  return useCallback(
    (message: string, resource: AgentResourceRef, name: string) => {
      const mine = queryClient.getQueryData<MyPermissions>(
        qk.organizations.permissions(activeOrgId ?? "current"),
      );
      const offers = mine?.permissions.some((entry) => entry.permission === Perm.agentsEdit);
      if (!offers) toast.success(message);
      else
        toast.success(message, {
          action: { label: t("addToAgent"), onClick: () => open({ resource, name }) },
        });
    },
    [activeOrgId, open, queryClient, t],
  );
}
