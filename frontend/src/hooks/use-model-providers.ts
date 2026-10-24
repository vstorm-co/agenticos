"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { invalidateSpeechSettings } from "@/lib/dictation-api";
import { qk } from "@/lib/query-keys";
import type { ModelApi, ModelProfile, ModelProfileList, ProviderCatalog } from "@/types/providers";
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
  /**
   * Which API the requests go to. Accepted only for providers whose catalog entry
   * lists `apis`; omitted, the service stores the default for the endpoint.
   */
  api?: ModelApi | null;
}

/**
 * Whether an organization's models are known, still coming, or unreadable.
 *
 * `loaded` is the only one of the three that makes an empty list a fact about
 * the organization.
 */
export type ProfilesStatus = "loaded" | "pending" | "failed";

function profilesStatus(query: { isSuccess: boolean; isError: boolean }): ProfilesStatus {
  if (query.isSuccess) return "loaded";
  return query.isError ? "failed" : "pending";
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
/**
 * The deployment's provider catalog alone - names and marks - for a surface
 * that only labels providers, such as the dashboard's spend card, and has no
 * reason to read the organization's model profiles beside it.
 */
export function useProviderCatalog() {
  return useQuery({
    queryKey: qk.providers.catalog(),
    queryFn: () => apiClient.get<ProviderCatalog>("/providers/catalog"),
    // Fixed until the platform is redeployed.
    staleTime: Infinity,
  });
}

export function useModelProviders() {
  const tErrors = useTranslations("errors");
  const t = useTranslations("settings");
  const queryClient = useQueryClient();

  const catalog = useProviderCatalog();

  const profiles = useQuery({
    queryKey: qk.providers.modelProfiles(),
    queryFn: () => apiClient.get<ModelProfileList>("/providers/model-profiles"),
  });

  const invalidate = useCallback(
    // Not `providers.all()`: that prefix covers the catalog, which no mutation
    // can change and which every dialog on the page needs to stay open. Speech
    // to text yes: a profile is one of the credentials a recording is sent with.
    () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: qk.providers.modelProfiles() }),
        invalidateSpeechSettings(queryClient),
      ]),
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
    /**
     * What `profiles` currently is: the organization's answer, a placeholder
     * while the read is in flight, or a read that failed.
     *
     * Three states rather than two, because `?? []` collapses all three into the
     * same empty array and each owes the reader something different - a claim
     * about the organization, a wait, and a failure with a way to try again. A
     * pair of booleans would let a caller hold `loaded` and `failed` at once;
     * this cannot.
     */
    profilesStatus: profilesStatus(profiles),
    /** Read the profiles again - what a panel that could not list them offers. */
    refetchProfiles: invalidate,
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
  source: "live" | "curated" | "unlisted";
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

/** One model that draws. */
export interface ImageModel {
  id: string;
  name: string;
  /** When to reach for this one rather than another. */
  description: string;
}

/** One provider that can draw, and what may be chosen on it. */
export interface ImageProvider {
  provider: string;
  name: string;
  models: ImageModel[];
}

interface ImageProviderList {
  items: ImageProvider[];
  total: number;
}

/**
 * The providers that can generate an image, and their models.
 *
 * Both halves are the server's answer rather than this file's. Whether a provider
 * can draw is `supported_native_tools()` on the SDK's model class - three can
 * today, and the answer is derived so an upgrade needs nothing here - and which
 * models it offers is `app/core/catalog/image_models.json`, so a model released
 * this morning is a catalog entry rather than a frontend release.
 *
 * A catalog, not a listing: no credential is read, and this says nothing about
 * what the organization has a key for. The secret field beside it does that.
 */
export interface SpeechToTextModel {
  id: string;
  name: string;
  description: string;
}

export interface SpeechToTextProvider {
  provider: string;
  name: string;
  models: SpeechToTextModel[];
}

interface SpeechToTextProviderList {
  items: SpeechToTextProvider[];
  total: number;
  /** ISO-639-1 codes a recording may be pinned to. */
  languages: string[];
}

/**
 * Which providers can transcribe a voice note, and with which models.
 *
 * The server's answer, like the image catalog beside it, and the filtering is the
 * part that matters: an entry whose credential is not a plain API key, or whose
 * API shape has no client, never reaches here - a picker entry that fails when
 * somebody sends a voice note is worse than one that is absent.
 *
 * A catalog, not a listing: no credential is read. Which keys a provider has is
 * the key picker's to say (`SpeechKeyField`), from the vault itself.
 */
export function useSpeechToTextProviders() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.providers.speechToTextModels(),
    queryFn: () => apiClient.get<SpeechToTextProviderList>("/providers/speech-to-text-models"),
    retry: false,
  });

  return { providers: data?.items ?? [], languages: data?.languages ?? [], isLoading, isError };
}

export function useImageProviders() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.providers.imageModels(),
    queryFn: () => apiClient.get<ImageProviderList>("/providers/image-models"),
    // Fixed until the platform is redeployed, like the provider catalog.
    staleTime: Infinity,
    retry: false,
  });

  return { providers: data?.items ?? [], isLoading, isError };
}

/** One voice a provider offers to every account. */
export interface TextToSpeechVoice {
  id: string;
  name: string;
  description: string;
}

/** One model that speaks, with the voices it can speak in. */
export interface TextToSpeechModel {
  id: string;
  name: string;
  description: string;
  max_characters: number;
  takes_instructions: boolean;
  /** Empty where the provider's voices belong to the account. */
  voices: TextToSpeechVoice[];
}

/** One provider that can speak, and what may be chosen on it. */
export interface TextToSpeechProvider {
  provider: string;
  name: string;
  formats: string[];
  /** Whether a binding names one of the account's own voices by id. */
  account_voices: boolean;
  models: TextToSpeechModel[];
}

interface TextToSpeechProviderList {
  items: TextToSpeechProvider[];
  total: number;
}

/**
 * The providers that can speak a text aloud, with their models and voices.
 *
 * The catalog is `app/core/catalog/text_to_speech_models.json`, served whole: a
 * model or a voice released this morning is a catalog entry rather than a frontend
 * release. ElevenLabs lists no voices because its voices belong to the account,
 * and `account_voices` says so. No credential is read.
 */
export function useTextToSpeechProviders() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.providers.textToSpeechModels(),
    queryFn: () => apiClient.get<TextToSpeechProviderList>("/providers/text-to-speech-models"),
    // Fixed until the platform is redeployed, like the provider catalog.
    staleTime: Infinity,
    retry: false,
  });

  return { providers: data?.items ?? [], isLoading, isError };
}

/** One model that makes video, and what it can make. */
export interface VideoModel {
  id: string;
  name: string;
  description: string;
  min_seconds: number;
  max_seconds: number;
  /** Whether a call may ask for a length; where not, the model decides its own. */
  duration_choosable: boolean;
  /** The first is the default. */
  aspect_ratios: string[];
  /** The first is the default. */
  resolutions: string[];
  audio: "always" | "optional" | "never";
  first_frame: boolean;
}

/** One provider that can make video, and what may be chosen on it. */
export interface VideoProvider {
  provider: string;
  name: string;
  models: VideoModel[];
}

interface VideoProviderList {
  items: VideoProvider[];
  total: number;
}

/**
 * The providers that can make a video, and what each of their models can make.
 *
 * The catalog is `app/core/catalog/video_models.json`, served whole, so the
 * Builder offers only the lengths, shapes and resolutions the chosen model
 * renders. No credential is read.
 */
export function useVideoProviders() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.providers.videoModels(),
    queryFn: () => apiClient.get<VideoProviderList>("/providers/video-models"),
    // Fixed until the platform is redeployed, like the provider catalog.
    staleTime: Infinity,
    retry: false,
  });

  return { providers: data?.items ?? [], isLoading, isError };
}
