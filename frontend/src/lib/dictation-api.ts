import type { QueryClient } from "@tanstack/react-query";

import { apiClient, sendWithProgress, type UploadProgress } from "@/lib/api-client";
import { ApiError, parseErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { DictationEngine, RecordingFormat } from "@/types/organization";

export type { RecordingFormat };

/** Whether the composer can dictate to one agent, as the server resolves it. */
export interface DictationStatus {
  /** The organization's engine for `/chat`. */
  engine: DictationEngine;
  /**
   * The engine is `server`, a provider and model resolve for this agent - its
   * published override or the organization's - the catalog offers them, and
   * the organization holds a credential for the provider.
   */
  ready: boolean;
  /**
   * `ready` without the `/chat` engine: a provider, a model and a credential
   * resolve for this agent. What a hosted page or a widget on `server` needs.
   */
  server_available: boolean;
  max_seconds: number;
  /** Where a recording would go: the agent's override or the organization's. */
  provider: string | null;
  /** What to record in for that provider, as the backend's catalog says. */
  format: RecordingFormat;
}

/**
 * Sends one recording somewhere that turns it into text.
 *
 * The composer posts to its agent, a hosted page to its public key; the hook
 * that records takes this rather than knowing either. `onProgress` hears how
 * much of the recording has gone up, and 1 once all of it has. It rejects with
 * an `ApiError` carrying the server's `details.reason`, a `TypeError` when the
 * request never left, or an `AbortError` when it was cancelled.
 */
export type DictationSend = (
  recording: Blob,
  seconds: number,
  signal: AbortSignal,
  onProgress: UploadProgress,
) => Promise<string>;

/** One agent's or one channel bot's share of the organization's transcription. */
export interface TranscriptionUsageGroup {
  name: string;
  /** Audio seconds across the recordings whose length is known. */
  seconds: number;
  count: number;
}

/** `GET /ml/calls/summary`: successful transcriptions over a window, added up. */
export interface TranscriptionUsage {
  days: number;
  /** An under-count whenever `count_unknown_length` is not 0. */
  seconds: number;
  count: number;
  /** Recordings no provider or platform stated a length for. */
  count_unknown_length: number;
  by_agent: (TranscriptionUsageGroup & { agent_id: string })[];
  by_channel: (TranscriptionUsageGroup & { channel_bot_id: string })[];
}

/** Read how much this organization transcribed over the last `days`. Needs `runs:view`. */
export function transcriptionUsage(days: number): Promise<TranscriptionUsage> {
  return apiClient.get<TranscriptionUsage>("/ml/calls/summary", {
    params: { ml_service: "speech_to_text", days: String(days) },
  });
}

/** Read whether dictation to this agent would reach an engine. */
export function dictationStatus(agentId: string): Promise<DictationStatus> {
  return apiClient.get<DictationStatus>(`/agents/${agentId}/dictation`);
}

/**
 * Refetch everything that says whether speech can be transcribed here.
 *
 * Every agent's readiness, and which providers the catalog marks usable: the
 * organization's voice settings, a publish or promotion, a model profile and a
 * vault key each change one or both, and none of them knows which agents it
 * touched.
 */
export function invalidateSpeechSettings(queryClient: QueryClient): Promise<void> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: qk.dictation.all() }),
    queryClient.invalidateQueries({ queryKey: qk.providers.speechToTextModels() }),
  ]).then(() => undefined);
}

/**
 * Why a dictation did not become text.
 *
 * The first six are the server's own `details.reason`; the last two are what
 * the browser can tell without one - a 429 from a rate limit, and a request
 * that never reached the server at all.
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
  "audio/wav": "wav",
};

/** The form both dictation routes read: the recording, and how long it is. */
function dictationForm(recording: Blob, seconds: number): FormData {
  const base = recording.type.split(";")[0]!.trim();
  const file = new File([recording], `recording.${EXTENSION[base] ?? "webm"}`, {
    type: recording.type,
  });
  const form = new FormData();
  form.append("file", file);
  form.append("duration", String(Math.max(0, seconds)));
  return form;
}

/**
 * Send one composer recording for transcription; the audio is not kept.
 *
 * `seconds` is how long the browser recorded, sent as `duration` beside the
 * file. The server records it with the call's usage only where the provider
 * states no length of its own, and clamps it to the organization's longest
 * dictation - it is the browser's word, not a measurement.
 *
 * The progress is the upload to this app's own route, which reads the whole
 * body before passing it on: at 1 the recording has reached the console's
 * server, not yet the platform.
 */
export async function dictate(
  agentId: string,
  recording: Blob,
  seconds: number,
  signal: AbortSignal,
  onProgress: UploadProgress,
): Promise<string> {
  const { text } = await apiClient.upload<{ text: string }>(
    `/agents/${agentId}/dictation`,
    dictationForm(recording, seconds),
    { signal, onProgress },
  );
  return text;
}

/**
 * Send a hosted page visitor's recording; the audio is not kept.
 *
 * Straight to the API rather than through a route handler of ours, the way the
 * page's file uploads go: the page has no session to proxy, and what admits the
 * request is the public key in the path and the visitor's continuity key in
 * `X-Visitor-Key` - a header, because the key is a bearer credential for the
 * whole transcript and a query string lands in access logs. A refusal becomes
 * the same `ApiError` the composer's does, so `dictationReason` reads it alike.
 * By `sendWithProgress` rather than `fetch`, so the visitor sees it go up too.
 */
export async function dictateOnPage(
  target: { apiUrl: string; publicKey: string; visitorKey: string },
  recording: Blob,
  seconds: number,
  signal: AbortSignal,
  onProgress: UploadProgress,
): Promise<string> {
  const response = await sendWithProgress(
    `${target.apiUrl}/api/v1/embed/${encodeURIComponent(target.publicKey)}/dictation`,
    {
      method: "POST",
      body: dictationForm(recording, seconds),
      headers: { "X-Visitor-Key": target.visitorKey },
      signal,
    },
    onProgress,
  );
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, parseErrorMessage(body), body);
  return (body as { text: string }).text;
}

/**
 * The reason a dictation request failed, or `null` when the person cancelled it.
 *
 * The server's `details.reason` wins. A 413 without one is the body-limit
 * middleware refusing before the route ran, which is the same answer for the
 * person: the recording is too large. A 404 is an embed whose operator has
 * since turned server dictation off, which for the person is the same as it not
 * being set up. A `TypeError` is what `fetch`, and `sendWithProgress` like it,
 * throws when the request never left the browser.
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
    if (error.status === 404) return "not_configured";
  }
  return "provider_error";
}

/** How long a rate-limited dictation has to wait, from the 429's details. */
export function retryAfterSeconds(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null;
  const seconds = error.details?.retry_after_seconds;
  return typeof seconds === "number" && seconds > 0 ? Math.ceil(seconds) : null;
}
