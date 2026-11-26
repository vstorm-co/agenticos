"use client";

import { useCallback, useState } from "react";

import type { EmbeddingProbeResult } from "@/lib/embedding-probe-api";

interface Tested {
  result: EmbeddingProbeResult;
  values: string;
}

/**
 * Holds a test result and gives its token back only while the form still holds
 * the values that were tested.
 *
 * The server binds the token to those values and refuses any other, so a token
 * kept after an edit would only turn into a refusal on Save. Comparing the
 * serialised values here lets the button say so first. A failed result keeps
 * no token: the result stays so its causes can be shown.
 */
export function useProbeGate<T>(values: T) {
  const [tested, setTested] = useState<Tested | null>(null);
  const [testing, setTesting] = useState(false);
  const current = JSON.stringify(values);

  const test = useCallback(
    async (run: () => Promise<EmbeddingProbeResult>) => {
      const at = current;
      setTesting(true);
      try {
        const result = await run();
        setTested({ result, values: at });
      } finally {
        setTesting(false);
      }
    },
    [current],
  );

  // A result for other values describes something no longer in the form.
  const live = tested !== null && tested.values === current ? tested.result : null;
  const token = live?.passed ? live.probe_token : null;
  const status: "idle" | "testing" | "passed" | "failed" = testing
    ? "testing"
    : live === null
      ? "idle"
      : live.passed
        ? "passed"
        : "failed";

  return { status, result: live, token, test };
}
