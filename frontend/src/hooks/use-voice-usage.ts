"use client";

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query-keys";
import { voiceUsage } from "@/lib/voice-api";
import type { VoiceUsage } from "@/types/voice";

/**
 * The organization's call minutes for calls started in `[start, end)`, by agent (#54).
 *
 * `start` and `end` are instants, as `periodStart`/`periodEnd` give them.
 * `enabled` is how a caller without `runs:view` opts out: the route names
 * agents and refuses anyone who may not read runs, so asking would only fetch
 * a 403.
 */
export function useVoiceUsage(
  range: { start: string; end: string },
  options: { enabled: boolean },
): { usage: VoiceUsage | null; isLoading: boolean; error: unknown; refetch: () => void } {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: qk.voice.usage(range.start, range.end),
    queryFn: () => voiceUsage(range.start, range.end),
    enabled: options.enabled,
  });
  return { usage: data ?? null, isLoading, error, refetch: () => void refetch() };
}
