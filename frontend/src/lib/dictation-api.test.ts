import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";

import { QueryClient } from "@tanstack/react-query";

import {
  dictate,
  dictationReason,
  dictationStatus,
  invalidateSpeechSettings,
  retryAfterSeconds,
} from "./dictation-api";

const { upload, get } = vi.hoisted(() => ({ upload: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { upload, get } }));

/** A refusal the way the backend writes one: the envelope, with `details`. */
function refusal(status: number, details: Record<string, unknown> | null = null): ApiError {
  return new ApiError(status, "refused", {
    error: { code: "REFUSED", message: "refused", details },
  });
}

beforeEach(() => {
  upload.mockReset();
  upload.mockResolvedValue({ text: "hello there" });
});

describe("dictate", () => {
  it.each([
    ["audio/webm;codecs=opus", "recording.webm"],
    ["audio/ogg;codecs=opus", "recording.ogg"],
    ["audio/mp4", "recording.mp4"],
    ["audio/x-unknown", "recording.webm"],
  ])("sends a %s recording as %s to the agent's dictation route", async (type, name) => {
    const signal = new AbortController().signal;

    const text = await dictate("a1", new Blob(["audio"], { type }), signal);

    expect(text).toBe("hello there");
    expect(upload).toHaveBeenCalledOnce();
    const [endpoint, file, options] = upload.mock.calls[0]!;
    expect(endpoint).toBe("/agents/a1/dictation");
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe(name);
    expect((file as File).type).toBe(type);
    expect(options).toEqual({ signal });
  });
});

describe("dictationReason", () => {
  it.each<[string, unknown, string | null]>([
    ["the server's not_configured", refusal(503, { reason: "not_configured" }), "not_configured"],
    ["the server's empty", refusal(400, { reason: "empty" }), "empty"],
    [
      "the server's unsupported_type",
      refusal(400, { reason: "unsupported_type" }),
      "unsupported_type",
    ],
    ["the server's too_large", refusal(400, { reason: "too_large" }), "too_large"],
    ["the server's provider_error", refusal(503, { reason: "provider_error" }), "provider_error"],
    ["the server's timeout", refusal(503, { reason: "timeout" }), "timeout"],
    ["a 429 from the rate limiter", refusal(429, { retry_after_seconds: 40 }), "rate_limited"],
    ["a 413 from the body-limit middleware", refusal(413), "too_large"],
    ["a reason the client does not know", refusal(400, { reason: "novel" }), "provider_error"],
    ["any other refusal", refusal(500), "provider_error"],
    ["a fetch that never left the browser", new TypeError("Failed to fetch"), "offline"],
    ["the person cancelling", new DOMException("aborted", "AbortError"), null],
    ["something thrown that is not an error", "boom", "provider_error"],
  ])("maps %s", (_label, error, expected) => {
    expect(dictationReason(error)).toBe(expected);
  });
});

describe("retryAfterSeconds", () => {
  it("reads the wait off a 429, rounded up to whole seconds", () => {
    expect(retryAfterSeconds(refusal(429, { retry_after_seconds: 39.2 }))).toBe(40);
  });

  it.each<[string, unknown]>([
    ["a 429 without a wait", refusal(429)],
    ["a 429 with a wait that is not a number", refusal(429, { retry_after_seconds: "soon" })],
    ["a 429 with nothing to wait for", refusal(429, { retry_after_seconds: 0 })],
    ["another status", refusal(503, { retry_after_seconds: 40 })],
    ["something that is not a refusal", new Error("boom")],
  ])("is null for %s", (_label, error) => {
    expect(retryAfterSeconds(error)).toBeNull();
  });
});

describe("dictationStatus", () => {
  it("asks the agent's dictation route", async () => {
    const answer = { engine: "server", ready: true, max_seconds: 60, provider: "groq" };
    get.mockResolvedValueOnce(answer);

    await expect(dictationStatus("a1")).resolves.toEqual(answer);
    expect(get).toHaveBeenCalledWith("/agents/a1/dictation");
  });
});

describe("invalidateSpeechSettings", () => {
  it("marks every agent's readiness and the provider catalog stale, and nothing else", async () => {
    const client = new QueryClient();
    client.setQueryData(["dictation", "a1"], { ready: true });
    client.setQueryData(["dictation", "a2"], { ready: false });
    client.setQueryData(["providers", "speech-to-text-models"], { items: [] });
    client.setQueryData(["providers", "catalog"], { items: [] });

    await invalidateSpeechSettings(client);

    const stale = (key: string[]) => client.getQueryState(key)?.isInvalidated;
    expect(stale(["dictation", "a1"])).toBe(true);
    expect(stale(["dictation", "a2"])).toBe(true);
    expect(stale(["providers", "speech-to-text-models"])).toBe(true);
    expect(stale(["providers", "catalog"])).toBe(false);
  });
});
