/**
 * Server-side API client for calling the FastAPI backend.
 * This module is used by Next.js API routes to proxy requests.
 * IMPORTANT: This file should only be imported in server-side code (API routes, Server Components).
 */

import { type NextRequest, NextResponse } from "next/server";

import type { BffErrorCode } from "@/lib/bff-errors";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/**
 * A refusal minted by a BFF route itself, as `{ code }` on the wire.
 *
 * A route handler sits outside the `[locale]` segment, so it cannot write the
 * refusal as a sentence in the caller's language - it used to write English,
 * which every toast rendered verbatim under every locale (#603). The client
 * resolves the code against the `errors` namespace via `getErrorMessage`.
 */
export function bffRefusal(code: BffErrorCode, status: number): NextResponse {
  return withNoStore(NextResponse.json({ code }, { status }));
}

/**
 * A BFF route's JSON answer, stamped `no-store`.
 *
 * Every answer on this surface depends on the caller's cookie, permission set
 * and organization header, so a list refetched right after a write - members
 * after an invite, integrations after a revoke - must reach the server rather
 * than be served from cache. `platformProxy` stamps this on any unmarked
 * response (the #230 fix); a hand-rolled `backendFetch` route owes the same
 * header, and this is the one place it is applied so no route can forget it.
 */
export function bffJson<T>(data: T, init?: ResponseInit): NextResponse {
  return withNoStore(NextResponse.json(data, init));
}

/** Stamp `Cache-Control: no-store`, unless the caller already set a policy. */
function withNoStore(response: NextResponse): NextResponse {
  if (!response.headers.has("cache-control")) {
    response.headers.set("Cache-Control", "no-store");
  }
  return response;
}

export class BackendApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown,
    // The response headers, retained so a BFF route can forward `Retry-After`
    // on a 429 - a rate limit is a wait, and the interval is in a header the
    // route would otherwise drop (#1047).
    public headers?: Headers,
  ) {
    // i18n-exempt: an Error message for a log, never rendered.
    super(`Backend API error: ${status} ${statusText}`);
    this.name = "BackendApiError";
  }
}

/**
 * Forward the incoming caller's address to the backend on an auth call.
 *
 * The auth rate limiter keys its per-IP bucket on `caller_ip`, which reads
 * `X-Forwarded-For` only when the deployment trusts it. Without this the backend
 * sees the frontend container and the whole deployment shares one bucket, so a
 * handful of logins lock everyone out (#1047). Forwarded verbatim: the backend
 * reads the rightmost hop, and the trust setting is what a deployment turns on
 * once its proxy topology makes that hop the real client - see
 * `docs/configuration.md`.
 */
export function forwardedFor(request: NextRequest): Record<string, string> {
  const forwarded = request.headers.get("x-forwarded-for");
  return forwarded ? { "x-forwarded-for": forwarded } : {};
}

/**
 * Forward the backend's 429 to the browser as a rate-limit result.
 *
 * The backend answers a rate limit with its `RATE_LIMIT_EXCEEDED` envelope and a
 * `Retry-After` header; an auth route that flattened it to "login failed" or
 * "session expired" (clearing the cookies) told the caller the wrong thing and
 * dropped the wait interval (#1047). This passes the envelope through - the
 * client resolves its code and `retry_after_seconds` - and re-sets `Retry-After`.
 */
export function forwardRateLimit(error: BackendApiError): NextResponse {
  const response = bffJson(error.data ?? { error: { code: "RATE_LIMIT_EXCEEDED" } }, {
    status: 429,
  });
  const retryAfter = error.headers?.get("retry-after");
  if (retryAfter) {
    response.headers.set("Retry-After", retryAfter);
  }
  return response;
}

interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
  /** Return raw text instead of parsing as JSON */
  raw?: boolean;
}

/**
 * Make a request to the FastAPI backend.
 * This should only be called from Next.js API routes or Server Components.
 */
export async function backendFetch<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { params, body, raw, ...fetchOptions } = options;

  let url = `${BACKEND_URL}${endpoint}`;

  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  // Determine content type - don't set for FormData (browser will set with boundary)
  const headers: Record<string, string> = {};
  if (body instanceof FormData) {
    // Let the browser set Content-Type with the multipart boundary
  } else {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, {
    ...fetchOptions,
    headers: {
      ...headers,
      ...fetchOptions.headers,
    },
    body,
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = null;
    }
    throw new BackendApiError(response.status, response.statusText, errorData, response.headers);
  }

  const text = await response.text();
  if (!text) {
    return null as T;
  }

  if (raw) {
    return text as T;
  }

  return JSON.parse(text);
}

/**
 * Forward authorization header from the incoming request to the backend.
 */
export function getAuthHeaders(authHeader: string | null): Record<string, string> {
  if (!authHeader) {
    return {};
  }
  return { Authorization: authHeader };
}
