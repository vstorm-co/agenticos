"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import {
  createServiceConnection,
  deleteServiceConnection,
  listServiceConnections,
  updateServiceConnection,
  type ServiceConnectionInput,
  type ServiceConnectionPatch,
  type ServiceConnectionRecord,
} from "@/lib/service-connections-api";
import { qk } from "@/lib/query-keys";

interface UseServiceConnectionsResult {
  connections: ServiceConnectionRecord[];
  isLoading: boolean;
  error: string | null;
  create: (input: ServiceConnectionInput) => Promise<ServiceConnectionRecord>;
  update: (id: string, patch: ServiceConnectionPatch) => Promise<ServiceConnectionRecord>;
  remove: (id: string) => Promise<void>;
}

/**
 * The servers this organization's collections may embed through or OCR with -
 * its own rows and the deployment-wide ones, in one list, because a picker
 * offers both and a person choosing does not care which table owns the row.
 *
 * `enabled` is what lets a picker hold the hook without firing the request: the
 * embedding picker only needs the list once a provider reached through a connection is chosen, and a
 * section hidden for want of `connections:manage` should ask for nothing rather
 * than collect a refusal.
 */
export function useServiceConnections(enabled = true): UseServiceConnectionsResult {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const {
    data: connections = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.serviceConnections.list(),
    queryFn: listServiceConnections,
    enabled,
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.serviceConnections.all() });
  }, [queryClient]);

  const create = useCallback(
    async (input: ServiceConnectionInput) => {
      const created = await createServiceConnection(input);
      await invalidate();
      return created;
    },
    [invalidate],
  );

  const update = useCallback(
    async (id: string, patch: ServiceConnectionPatch) => {
      const updated = await updateServiceConnection(id, patch);
      await invalidate();
      return updated;
    },
    [invalidate],
  );

  const remove = useCallback(
    async (id: string) => {
      await deleteServiceConnection(id);
      await invalidate();
    },
    [invalidate],
  );

  return {
    connections,
    isLoading: enabled && isLoading,
    error: queryError
      ? getErrorMessage(queryError, tErrors, t("failedLoadServiceConnections"))
      : null,
    create,
    update,
    remove,
  };
}
