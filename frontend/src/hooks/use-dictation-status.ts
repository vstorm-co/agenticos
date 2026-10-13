"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { dictationStatus, type DictationStatus } from "@/lib/dictation-api";
import { qk } from "@/lib/query-keys";

/**
 * Whether the composer can dictate to this agent, and on which provider.
 *
 * Per agent because an agent's published speech-to-text override can name a
 * provider of its own: it can make server dictation work where the
 * organization has none, and it decides the format the browser records in -
 * Mistral takes WAV where the others take WebM.
 *
 * `agentId` null asks nothing, which is how the composer keeps this off the
 * network until the organization's engine is `server` and an agent is chosen.
 * The previous agent's answer is held while the next one's loads, so switching
 * agents does not cross the microphone out for a frame.
 */
export function useDictationStatus(agentId: string | null): DictationStatus | null {
  const { data } = useQuery({
    queryKey: qk.dictation.agent(agentId ?? ""),
    queryFn: () => dictationStatus(agentId as string),
    enabled: agentId !== null,
    placeholderData: keepPreviousData,
  });
  return agentId === null ? null : (data ?? null);
}
