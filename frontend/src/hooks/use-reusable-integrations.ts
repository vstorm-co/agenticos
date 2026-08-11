"use client";

import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type {
  ConnectorInfo,
  ConnectorList,
  SyncSourceCreate,
  SyncSourceList,
  SyncSourceRead,
} from "@/lib/rag-api";
import type { KnowledgeBase } from "@/types";

interface UseReusableIntegrationsResult {
  integrations: SyncSourceRead[];
  connectors: ConnectorInfo[];
  isLoading: boolean;
  error: string | null;
  create: (data: SyncSourceCreate) => Promise<SyncSourceRead>;
  remove: (sourceId: string) => Promise<void>;
  cloneInto: (sourceId: string, target: KnowledgeBase, name: string) => Promise<void>;
}

/**
 * The organization's integrations that belong to no collection yet.
 *
 * `GET /orgs/{id}/integrations` answers with every integration the organization
 * has, assigned or not - it was written for a page that listed both. The
 * assigned ones are now shown by the collection they feed, on `/kb/{id}`, so
 * this keeps only the rest: the ones with nowhere else to appear, which would
 * otherwise be configured, stored, and then unreachable.
 *
 * `orgId` is nullable so a caller can hold the hook without firing the request
 * - the endpoint is owner/admin-only, and a member who is shown nothing should
 * also ask for nothing rather than collect a 403.
 *
 * Cloning goes through the *destination* collection's route, which resolves the
 * origin inside the caller's organization before it decrypts anything. The
 * origin row is left where it is: an integration usable once would not be
 * reusable.
 */
export function useReusableIntegrations(orgId: string | null): UseReusableIntegrationsResult {
  const t = useTranslations("kb");
  const queryClient = useQueryClient();

  const {
    data: integrations = [],
    isLoading,
    error: queryError,
  } = useQuery({
    queryKey: qk.integrations.reusable(orgId ?? ""),
    queryFn: async () => {
      const list = await apiClient.get<SyncSourceList>(`/orgs/${orgId}/integrations`);
      return list.items.filter((source) => !source.collection_name);
    },
    enabled: Boolean(orgId),
  });

  const { data: connectors = [] } = useQuery({
    queryKey: qk.integrations.connectors(orgId ?? ""),
    queryFn: async () =>
      (await apiClient.get<ConnectorList>(`/orgs/${orgId}/integrations/connectors`)).items,
    enabled: Boolean(orgId),
  });

  const error =
    queryError instanceof Error
      ? queryError.message
      : queryError
        ? t("failedLoadReusableIntegrations")
        : null;

  const writeCache = useCallback(
    (updater: (prev: SyncSourceRead[]) => SyncSourceRead[]) =>
      queryClient.setQueryData<SyncSourceRead[]>(
        qk.integrations.reusable(orgId ?? ""),
        (prev = []) => updater(prev),
      ),
    [queryClient, orgId],
  );

  const create = useCallback<UseReusableIntegrationsResult["create"]>(
    async (data) => {
      try {
        const created = await apiClient.post<SyncSourceRead>(`/orgs/${orgId}/integrations`, {
          ...data,
          // The wizard builds a payload with this field on it. Sending it null
          // explicitly is what keeps the row reusable rather than pinning it to
          // whichever collection happened to be in the form.
          collection_name: null,
        });
        writeCache((prev) => [created, ...prev]);
        toast.success(t("integrationSaved"));
        return created;
      } catch (cause) {
        // Reported here and raised again: the connector's own refusal ("Invalid
        // connector config: …") is the only sentence that says what to change,
        // and the wizard has to stay open on the step holding the answer.
        toast.error(cause instanceof Error ? cause.message : t("failedSaveIntegration"));
        throw cause;
      }
    },
    [orgId, writeCache, t],
  );

  const remove = useCallback<UseReusableIntegrationsResult["remove"]>(
    async (sourceId) => {
      try {
        await apiClient.delete(`/orgs/${orgId}/integrations/${sourceId}`);
        writeCache((prev) => prev.filter((source) => source.id !== sourceId));
        toast.success(t("integrationRemoved"));
      } catch (cause) {
        toast.error(cause instanceof Error ? cause.message : t("failedRemoveIntegration"));
      }
    },
    [orgId, writeCache, t],
  );

  const cloneInto = useCallback<UseReusableIntegrationsResult["cloneInto"]>(
    async (sourceId, target, name) => {
      try {
        await apiClient.post<SyncSourceRead>(`/kb/${target.id}/sync-sources/${sourceId}/clone`, {
          collection_name: target.collection_name,
          name,
        });
        toast.success(t("integrationAddedTo", { name: target.name }));
      } catch (cause) {
        toast.error(cause instanceof Error ? cause.message : t("failedUseIntegration"));
        throw cause;
      }
    },
    [t],
  );

  return { integrations, connectors, isLoading, error, create, remove, cloneInto };
}
