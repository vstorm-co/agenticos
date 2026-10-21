"use client";

import { useQuery } from "@tanstack/react-query";

import { dictationStatus, type DictationStatus } from "@/lib/dictation-api";
import { qk } from "@/lib/query-keys";

/** One agent's dictation readiness, as far as it is known. */
export interface DictationStatusRead {
  /** The agent's answer; null without an agent, while it loads, and when the read failed. */
  status: DictationStatus | null;
  /** The read failed: `status` is null because nobody knows, not because it is on its way. */
  failed: boolean;
}

/**
 * Whether the composer can dictate to this agent, and on which provider.
 *
 * Per agent because an agent's published speech-to-text override can name a
 * provider of its own: it can make server dictation work where the
 * organization has none, and it decides the format the browser records in -
 * WAV, unless the deployment accepts compressed audio and the provider takes WebM.
 *
 * `agentId` null asks nothing, which is how the composer keeps this off the
 * network until an agent is chosen.
 * The previous agent's answer is not held while the next one's loads: a press
 * in that moment would record in the previous agent's format and call it ready,
 * so the microphone is crossed out until this agent answers.
 */
export function useDictationStatus(agentId: string | null): DictationStatusRead {
  const { data, isError } = useQuery({
    queryKey: qk.dictation.agent(agentId ?? ""),
    queryFn: () => dictationStatus(agentId as string),
    enabled: agentId !== null,
  });
  if (agentId === null) return { status: null, failed: false };
  return { status: data ?? null, failed: isError && data === undefined };
}
