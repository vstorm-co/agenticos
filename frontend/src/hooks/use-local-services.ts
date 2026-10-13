"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { getErrorMessage } from "@/lib/api-error";
import {
  createLocalService,
  deleteLocalService,
  listLocalServices,
  updateLocalService,
  type LocalServiceInput,
  type LocalServicePatch,
  type LocalServiceRecord,
} from "@/lib/local-services-api";
import { qk } from "@/lib/query-keys";

interface UseLocalServicesResult {
  services: LocalServiceRecord[];
  isLoading: boolean;
  error: string | null;
  create: (input: LocalServiceInput) => Promise<LocalServiceRecord>;
  update: (id: string, patch: LocalServicePatch) => Promise<LocalServiceRecord>;
  remove: (id: string) => Promise<void>;
}

/**
 * The servers this organization's collections may embed through or OCR with -
 * its own rows and the deployment-wide ones, in one list, because a picker
 * offers both and a person choosing does not care which table owns the row.
 *
 * `enabled` is what lets a picker hold the hook without firing the request: the
 * embedding picker only needs the list once a keyless provider is chosen, and a
 * section hidden for want of `connections:manage` should ask for nothing rather
 * than collect a refusal.
 */
export function useLocalServices(enabled = true): UseLocalServicesResult {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();

  const {
    data: services = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.localServices.list(),
    queryFn: listLocalServices,
    enabled,
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.localServices.all() });
  }, [queryClient]);

  const create = useCallback(
    async (input: LocalServiceInput) => {
      const created = await createLocalService(input);
      await invalidate();
      return created;
    },
    [invalidate],
  );

  const update = useCallback(
    async (id: string, patch: LocalServicePatch) => {
      const updated = await updateLocalService(id, patch);
      await invalidate();
      return updated;
    },
    [invalidate],
  );

  const remove = useCallback(
    async (id: string) => {
      await deleteLocalService(id);
      await invalidate();
    },
    [invalidate],
  );

  return {
    services,
    isLoading: enabled && isLoading,
    error: queryError ? getErrorMessage(queryError, tErrors, t("failedLoadLocalServices")) : null,
    create,
    update,
    remove,
  };
}
