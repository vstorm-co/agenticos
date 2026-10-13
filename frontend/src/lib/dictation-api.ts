import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

/**
 * Why a dictation did not become text.
 *
 * The first six are the server's own `details.reason`; the last two are what
 * the browser can tell without one - a 429 from the per-user limit, and a
 * request that never reached the server at all.
 */
export type DictationReason =
  | "not_configured"
  | "empty"
  | "unsupported_type"
  | "too_large"
  | "provider_error"
  | "timeout"
  | "rate_limited"
  | "offline";

const SERVER_REASONS: ReadonlySet<string> = new Set([
  "not_configured",
  "empty",
  "unsupported_type",
  "too_large",
  "provider_error",
  "timeout",
]);

/** The file name the server's provider is handed, by the recording's base type. */
const EXTENSION: Record<string, string> = {
  "audio/webm": "webm",
  "audio/ogg": "ogg",
  "audio/mp4": "mp4",
};

/** Send one composer recording for transcription; the audio is not kept. */
export async function dictate(
  agentId: string,
  recording: Blob,
  signal: AbortSignal,
): Promise<string> {
  const base = recording.type.split(";")[0]!.trim();
  const file = new File([recording], `recording.${EXTENSION[base] ?? "webm"}`, {
    type: recording.type,
  });
  const { text } = await apiClient.upload<{ text: string }>(`/agents/${agentId}/dictation`, file, {
    signal,
  });
  return text;
}

/**
 * The reason a dictation request failed, or `null` when the person cancelled it.
 *
 * The server's `details.reason` wins. A 413 without one is the body-limit
 * middleware refusing before the route ran, which is the same answer for the
 * person: the recording is too large. A `TypeError` is what `fetch` throws when
 * the request never left the browser.
 */
export function dictationReason(error: unknown): DictationReason | null {
  // Not every runtime makes a `DOMException` an `Error`, so both are asked.
  if ((error instanceof DOMException || error instanceof Error) && error.name === "AbortError") {
    return null;
  }
  if (error instanceof TypeError) return "offline";
  if (error instanceof ApiError) {
    const reason = error.details?.reason;
    if (typeof reason === "string" && SERVER_REASONS.has(reason)) {
      return reason as DictationReason;
    }
    if (error.status === 429) return "rate_limited";
    if (error.status === 413) return "too_large";
  }
  return "provider_error";
}

/** How long a rate-limited dictation has to wait, from the 429's details. */
export function retryAfterSeconds(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null;
  const seconds = error.details?.retry_after_seconds;
  return typeof seconds === "number" && seconds > 0 ? Math.ceil(seconds) : null;
}
