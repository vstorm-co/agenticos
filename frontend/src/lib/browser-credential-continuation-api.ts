import { apiClient } from "./api-client";
import {
  browserCredentialRequest,
  type BrowserCredentialAudience,
} from "./browser-credentials-api";
import {
  decodeBrowserContinuation,
  isBrowserContinuationSource,
} from "./browser-credential-continuation";
import { isBrowserCredentialId } from "./browser-credential-review";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type {
  BrowserContinuationConfirmation,
  BrowserContinuationRequest,
  BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";

const path = (source: BrowserCredentialPlan) =>
  `/runs/${encodeURIComponent(source.run_id)}/browser-credential-plans/${encodeURIComponent(source.id)}/continuation`;

function requireSource(source: BrowserCredentialPlan) {
  if (!isBrowserContinuationSource(source)) {
    // i18n-exempt: fixed internal refusal; a fill or unknown submit never authorizes continuation.
    throw new Error("Browser continuation source unavailable");
  }
}

function receipt(
  value: unknown,
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
) {
  const parsed = decodeBrowserContinuation(value, audience, source);
  if (!parsed) {
    // i18n-exempt: fixed internal refusal; malformed payloads never reach rendered errors.
    throw new Error("Browser continuation response unavailable");
  }
  return parsed;
}

export function readBrowserContinuation(
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
  signal?: AbortSignal,
): Promise<BrowserCredentialContinuation | null> {
  return browserCredentialRequest(
    audience,
    async (options) => {
      requireSource(source);
      const value = await apiClient.get<unknown>(path(source), options);
      return value === null ? null : receipt(value, audience, source);
    },
    signal,
  );
}

export function requestBrowserContinuation(
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
  body: BrowserContinuationRequest,
): Promise<BrowserCredentialContinuation> {
  return browserCredentialRequest(audience, async (options) => {
    requireSource(source);
    if (!isBrowserCredentialId(body.request_id)) {
      // i18n-exempt: this UUID is retained before requesting native preparation.
      throw new Error("Browser continuation request identity unavailable");
    }
    const row = receipt(
      await apiClient.post<unknown>(
        path(source),
        { request_id: body.request_id },
        {
          ...options,
          retryAfterRefresh: false,
        },
      ),
      audience,
      source,
    );
    if (row.id !== body.request_id) {
      // i18n-exempt: a different request cannot settle this person's retained attempt.
      throw new Error("Browser continuation request identity mismatch");
    }
    return row;
  });
}

export function confirmBrowserContinuation(
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
  current: BrowserCredentialContinuation,
  body: BrowserContinuationConfirmation,
): Promise<BrowserCredentialContinuation> {
  return browserCredentialRequest(audience, async (options) => {
    requireSource(source);
    if (
      !decodeBrowserContinuation(current, audience, source) ||
      current.state !== "awaiting_confirmation" ||
      body.document_id !== current.document_id ||
      body.authorization_generation !== current.authorization_generation ||
      typeof body.approve !== "boolean" ||
      typeof body.keep_signed_in !== "boolean"
    ) {
      // i18n-exempt: stale, terminal or different observations cannot issue another decision.
      throw new Error("Browser continuation decision unavailable");
    }
    const row = receipt(
      await apiClient.post<unknown>(
        `${path(source)}/${encodeURIComponent(current.id)}/confirmation`,
        {
          document_id: body.document_id,
          authorization_generation: body.authorization_generation,
          approve: body.approve,
          keep_signed_in: body.keep_signed_in,
        },
        { ...options, retryAfterRefresh: false },
      ),
      audience,
      source,
    );
    if (
      row.id !== current.id ||
      row.document_id !== body.document_id ||
      row.authorization_generation !== body.authorization_generation ||
      (row.keep_signed_in !== null && row.keep_signed_in !== body.keep_signed_in)
    ) {
      // i18n-exempt: an uncertain decision cannot broaden persistence or change documents.
      throw new Error("Browser continuation decision identity mismatch");
    }
    return row;
  });
}
