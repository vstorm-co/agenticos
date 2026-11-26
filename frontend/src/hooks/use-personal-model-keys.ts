"use client";

import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenantGuard, useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import {
  agentModelConnection,
  listPersonalModelKeys,
  savePersonalModelKey,
  deletePersonalModelKey,
} from "@/lib/personal-model-keys-api";

export function usePersonalModelKeys(agentId: string | null = null) {
  const tenant = useTenantId();
  const user = useAuthStore((state) => state.user?.id);
  const guard = useTenantGuard();
  const client = useQueryClient();
  const scope = `${tenant ?? ""}:${user ?? ""}`;
  const lifecycle = {
    onMutate: () => ({ tenant, user, scope }),
    onSuccess: (
      _data: unknown,
      _variables: unknown,
      started: { tenant: string | null; user: string | undefined; scope: string } | undefined,
    ) => {
      if (started && guard(started.tenant) && useAuthStore.getState().user?.id === started.user)
        void client.invalidateQueries({ queryKey: qk.personalModelKeys.all(started.scope) });
    },
  };
  const status = useQuery({
    queryKey: qk.personalModelKeys.agent(scope, agentId),
    queryFn: agentId ? () => agentModelConnection(agentId) : skipToken,
    enabled: !!tenant && !!user && !!agentId,
  });
  const keys = useQuery({
    queryKey: qk.personalModelKeys.all(scope),
    queryFn: listPersonalModelKeys,
    enabled: !!tenant && !!user && agentId === null,
  });
  return {
    status,
    keys,
    save: useMutation({
      mutationFn: savePersonalModelKey,
      ...lifecycle,
      onError: (error, _variables, started) => {
        if (
          error instanceof ApiError &&
          error.code === "PERSONAL_MODEL_DESTINATION_CHANGED" &&
          started &&
          guard(started.tenant) &&
          useAuthStore.getState().user?.id === started.user
        )
          void client.invalidateQueries({ queryKey: qk.personalModelKeys.all(started.scope) });
      },
    }),
    remove: useMutation({ mutationFn: deletePersonalModelKey, ...lifecycle }),
  };
}
