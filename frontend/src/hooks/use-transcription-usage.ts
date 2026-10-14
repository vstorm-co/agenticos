"use client";

import { useQuery } from "@tanstack/react-query";

import { transcriptionUsage, type TranscriptionUsage } from "@/lib/dictation-api";
import { qk } from "@/lib/query-keys";

/**
 * How much this organization transcribed over the last `days` (#1797).
 *
 * `enabled` is how a caller without `runs:view` opts out, the bargain `useSpend`
 * strikes: the summary names agents and channel bots, so the route refuses a
 * caller who may not read runs, and asking would only fetch a 403. `null` while
 * loading and on any failure - the one line it feeds is supplementary, and a
 * refusal or an outage is not "nothing transcribed".
 */
export function useTranscriptionUsage(
  days: number,
  options: { enabled: boolean },
): TranscriptionUsage | null {
  const { data } = useQuery({
    queryKey: qk.ml.transcriptionUsage(days),
    queryFn: () => transcriptionUsage(days),
    enabled: options.enabled,
  });
  return data ?? null;
}
