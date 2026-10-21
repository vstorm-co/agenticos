"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { realtimeModels } from "@/lib/voice-api";

/**
 * Which providers can hold a voice conversation, with which models and voices
 * (#54). A catalog, not a listing: no credential is read - which keys a
 * provider has is the key picker's to say (`SpeechKeyField`).
 */
export function useRealtimeModels() {
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.providers.realtimeModels(),
    queryFn: realtimeModels,
    // Fixed until the platform is redeployed, like the other catalogs.
    staleTime: Infinity,
    retry: false,
  });
  return { providers: data?.items ?? [], isLoading, isError };
}
