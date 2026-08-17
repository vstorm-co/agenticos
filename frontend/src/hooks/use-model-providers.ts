"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ModelProfile, ModelProfileList, ProviderCatalog } from "@/types/providers";
export interface NewModelProfile {
  label: string;
  provider: string;
  model: string;
  /**
   * The vault secret to key it with. `null` only for a keyless provider that
   * carries an endpoint - a model server on this network authenticates nothing,
   * and the service refuses every other combination.
   */
  secret_id: string | null;
  /**
   * Where to send the request, when it is not the provider's public API. Accepted
   * only for providers with `supports_base_url`; the service refuses it for the
   * rest rather than storing a value the SDK would drop.
   */
  base_url?: string | null;
}

/**
 * The providers this deployment can reach, and the models an organization has
 * defined on them.
 *
 * Keys are not here. They live in the vault with every other secret, and a model
 * names one by id - there was a second store for them once, with its own form
 * and its own rotation, and two stores for one thing was two of everything.
 *
 * The catalog is fetched rather than listed in code. It says which shape of key
 * each provider takes, whether it accepts a custom endpoint and whether it can
 * run with no key at all - three questions a hardcoded list of four providers
 * answered wrongly for the other twenty.
 */
export function useModelProviders() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("settings");
  const queryClient = useQueryClient();

  const catalog = useQuery({
    queryKey: qk.providers.catalog(),
    queryFn: () => apiClient.get<ProviderCatalog>("/providers/catalog"),
    // Fixed until the platform is redeployed.
    staleTime: Infinity,
  });

  const profiles = useQuery({
    queryKey: qk.providers.modelProfiles(),
    queryFn: () => apiClient.get<ModelProfileList>("/providers/model-profiles"),
  });

  const invalidate = useCallback(
    // Not `providers.all()`: that prefix covers the catalog, which no mutation
    // can change and which every dialog on the page needs to stay open.
    () => queryClient.invalidateQueries({ queryKey: qk.providers.modelProfiles() }),
    [queryClient],
  );

  // `createProfile` does not toast its failure; the form that owns the fields
  // does, because every refusal it gets is about one of them.
  const createProfile = useMutation({
    mutationFn: (data: NewModelProfile) =>
      apiClient.post<ModelProfile>("/providers/model-profiles", data),
    onSuccess: async (profile) => {
      await invalidate();
      toast.success(t("modelAdded", { label: profile.label }));
    },
  });

  const deleteProfile = useMutation({
    mutationFn: (id: string) => apiClient.delete<void>(`/providers/model-profiles/${id}`),
    onSuccess: async () => {
      await invalidate();
      toast.success(t("modelRemoved"));
    },
    onError: (error) => toast.error(getErrorMessage(error, tErrors)),
  });

  return {
    catalog: catalog.data?.items ?? [],
    profiles: profiles.data?.items ?? [],
    isLoading: catalog.isLoading || profiles.isLoading,
    isFetching: catalog.isFetching || profiles.isFetching,
    createProfile,
    deleteProfile,
  };
}

/** One model a provider offers, as a picker needs it. */
export interface ProviderModel {
  id: string;
  name: string;
  /** Tokens the model accepts, when the provider says. */
  context_length?: number | null;
}

interface ProviderModelList {
  items: ProviderModel[];
  total: number;
  /**
   * Where the list came from: `live` if the provider answered, `curated` if
   * this deployment's own list was used because the provider publishes none or
   * could not be reached.
   */
  source: "live" | "curated";
}

/**
 * The models one provider offers, for the field where a model id is typed.
 *
 * Suggestions, never a constraint. A provider ships a model the morning after
 * this list was cached, and a picker that cannot express "that one" is a picker
 * somebody has to work around - so the field stays free text and this only
 * fills its dropdown.
 *
 * Cached for an hour rather than indefinitely: a catalog changes when a provider
 * ships something, which is on the order of weeks, but a deployment that added
 * its first key should not have to reload to see a list.
 */
export function useProviderModels(providerId: string) {
  const { data, isLoading } = useQuery({
    queryKey: qk.providers.models(providerId),
    queryFn: () => apiClient.get<ProviderModelList>(`/providers/${providerId}/models`),
    enabled: providerId !== "",
    staleTime: 60 * 60 * 1000,
    // An empty dropdown is the fallback the field is built for, so a provider
    // that cannot be reached must not retry three times behind an open form.
    retry: false,
  });

  return { models: data?.items ?? [], source: data?.source ?? null, isLoading };
}
