"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { voiceReadiness } from "@/lib/voice-api";
import type { VoiceCallSurface, VoiceReadiness } from "@/types/voice";

/**
 * Whether the selected agent can take a call (#54). A `null` agent asks
 * nothing; the previous agent's answer is not held while the next one's loads,
 * so the call button is crossed out until this agent answers - the dictation
 * rule. `embed` asks for a widget or a hosted page, which the embed form reads
 * before offering its voice switch.
 */
export function useVoiceReadiness(
  agentId: string | null,
  surface: VoiceCallSurface = "web",
): {
  readiness: VoiceReadiness | null;
  failed: boolean;
} {
  const { data, isError } = useQuery({
    queryKey: qk.voice.readiness(agentId ?? "", surface),
    queryFn: () => voiceReadiness(agentId as string, surface),
    enabled: agentId !== null,
  });
  if (agentId === null) return { readiness: null, failed: false };
  return { readiness: data ?? null, failed: isError && data === undefined };
}
