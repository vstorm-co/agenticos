"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import {
  deleteExternalAgent,
  listExternalAgents,
  refreshExternalAgent,
  registerExternalAgent,
} from "@/lib/external-agents-api";
import { qk } from "@/lib/query-keys";
import type { ExternalAgent, ExternalAgentCreate } from "@/types/external-agents";

interface UseExternalAgentsResult {
  agents: ExternalAgent[];
  isLoading: boolean;
  error: string | null;
  register: (input: ExternalAgentCreate) => Promise<ExternalAgent>;
  refresh: (id: string) => Promise<ExternalAgent>;
  remove: (id: string) => Promise<void>;
}

/**
 * The remote A2A agents registered in this organization (#2092).
 *
 * Writes return their promise rather than toasting, so the dialog that made one
 * can keep its form and say what the server refused - an address it may not
 * call, a page that is not an agent card.
 */
export function useExternalAgents(enabled = true): UseExternalAgentsResult {
  const t = useTranslations("remoteAgents");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const {
    data: agents = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.externalAgents.list(),
    queryFn: listExternalAgents,
    enabled,
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.externalAgents.all() });
  }, [queryClient]);

  const register = useCallback(
    async (input: ExternalAgentCreate) => {
      const created = await registerExternalAgent(input);
      await invalidate();
      return created;
    },
    [invalidate],
  );

  const refresh = useCallback(
    async (id: string) => {
      const refreshed = await refreshExternalAgent(id);
      await invalidate();
      return refreshed;
    },
    [invalidate],
  );

  const remove = useCallback(
    async (id: string) => {
      await deleteExternalAgent(id);
      await invalidate();
    },
    [invalidate],
  );

  return {
    agents,
    isLoading: enabled && isLoading,
    error: queryError ? getErrorMessage(queryError, tErrors, t("failedToLoad")) : null,
    register,
    refresh,
    remove,
  };
}
