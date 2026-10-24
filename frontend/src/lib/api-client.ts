/**
 * Client-side API client.
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 */

import { ApiError, parseErrorMessage } from "@/lib/api-error";
import { markRefreshed, refreshedRecently, withAuthLock } from "@/lib/auth-lock";
import { CONSOLE_TAB, CONSOLE_TAB_HEADER } from "@/lib/console-tab";
import { useAuthStore, useOrgStore } from "@/stores";

// Re-exported because this module was where `ApiError` lived and where the rest
// of the app still imports it from. Its definition moved to `api-error.ts` so
// that reading a refusal does not require pulling in the fetch client.
export { ApiError };

/** How much of a request's body has gone up, from 0 to 1. */
export type UploadProgress = (fraction: number) => void;

interface RequestOptions extends Omit<RequestInit, "body"> {
  /** Pairs allow a repeated key - FastAPI list params arrive as ?status=a&status=b. */
  params?: Record<string, string> | [string, string][];
  body?: unknown;
  /**
   * Report the body's progress as it is sent. The request then goes by
   * `XMLHttpRequest` rather than `fetch`, which reports none.
   */
  onProgress?: UploadProgress;
}

/** Statuses whose response may not carry a body; `new Response` refuses one. */
const NULL_BODY_STATUSES: ReadonlySet<number> = new Set([204, 205, 304]);

/**
 * A request by `XMLHttpRequest`, for the one thing `fetch` cannot do: say how
 * much of the body has gone up. `onProgress` hears each step, and 1 once the
 * last byte has left.
 *
 * It answers the way `fetch` does, so whoever reads the answer cannot tell the
 * two apart: a `Response` for any status, a `TypeError` when the request never
 * reached a server, and an `AbortError` when `signal` cancelled it. That is
 * what `dictationReason` reads a failure by - offline, or nobody's fault.
 *
 * Credentials follow `fetch`'s default: cookies go to this origin only.
 */
export function sendWithProgress(
  url: string,
  init: {
    method: string;
    headers: HeadersInit;
    body: XMLHttpRequestBodyInit | null;
    signal?: AbortSignal | null;
  },
  onProgress: UploadProgress,
): Promise<Response> {
  const { signal } = init;
  return new Promise<Response>((resolve, reject) => {
    // i18n-exempt: an exception's name and message, read by code, never shown
    const aborted = () => new DOMException("The request was aborted.", "AbortError");
    if (signal?.aborted) {
      reject(aborted());
      return;
    }
    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    const settle = () => signal?.removeEventListener("abort", onAbort);
    xhr.open(init.method, url);
    new Headers(init.headers).forEach((value, name) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.upload.onload = () => onProgress(1);
    xhr.onload = () => {
      settle();
      const headers = new Headers();
      for (const line of xhr
        .getAllResponseHeaders()
        .trim()
        .split(/[\r\n]+/)) {
        const colon = line.indexOf(":");
        if (colon > 0) headers.append(line.slice(0, colon).trim(), line.slice(colon + 1).trim());
      }
      resolve(
        new Response(NULL_BODY_STATUSES.has(xhr.status) ? null : xhr.responseText, {
          status: xhr.status,
          statusText: xhr.statusText,
          headers,
        }),
      );
    };
    xhr.onerror = () => {
      settle();
      // i18n-exempt: what `fetch` rejects with, read by code as "offline"
      reject(new TypeError("Failed to fetch"));
    };
    xhr.onabort = () => {
      settle();
      reject(aborted());
    };
    signal?.addEventListener("abort", onAbort);
    xhr.send(init.body);
  });
}

// The proxy route that mints a fresh access token from the refresh cookie.
const REFRESH_ENDPOINT = "/auth/refresh";

// These 401s reject a submitted credential, not the browser's existing session.
// Refreshing would resubmit the same bad credential and could sign out a valid
// session when the retried answer is refused too.
const NO_REFRESH_RETRY: ReadonlySet<string> = new Set([
  REFRESH_ENDPOINT,
  "/auth/password/change",
  "/auth/login",
  "/auth/ldap/login",
  "/auth/register",
  "/auth/password-reset/confirm",
  "/auth/magic-link/verify",
  "/auth/email-change/confirm",
  "/auth/oauth-callback",
]);

// Endpoints whose proxy route refreshes on the server when the access cookie has
// expired, and so spends the refresh cookie like a refresh does. Sent under the
// cross-tab auth lock; their own 401 recovery runs outside it, because the lock
// is not reentrant.
const SERVER_REFRESHING: ReadonlySet<string> = new Set(["/auth/me"]);

// Shared in-flight refresh promise so a burst of concurrent 401s triggers only
// ONE refresh round-trip. Reset once the refresh settles.
let refreshPromise: Promise<boolean> | null = null;

/**
 * Whether a refused refresh was refused because the cookie was an impersonation.
 *
 * The one refusal that is not "sign in again": the browser was acting as
 * somebody else and that has ended, so the request that hit the 401 must not be
 * replayed with whatever token a refresh would mint - it would run as the
 * administrator (#1044). Reported to the store, where `useImpersonation` takes
 * the exit.
 */
async function refusedAsEndedImpersonation(res: Response): Promise<boolean> {
  if (res.status !== 401) return false;
  try {
    const data = (await res.json()) as { code?: string };
    return data?.code === "IMPERSONATION_ENDED";
  } catch {
    return false;
  }
}

/**
 * Attempt a single token refresh, de-duplicating concurrent callers.
 * Resolves true on success (cookies + in-memory access token updated), false
 * if the refresh itself failed (caller should surface the original 401).
 *
 * Serialized across tabs by `withAuthLock`. A tab that waited behind another's
 * refresh finds the cookies already rotated and retries with them instead of
 * spending the refresh token a second time.
 */
function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = withAuthLock(() => {
      if (refreshedRecently()) return Promise.resolve(true);
      return fetch(`/api${REFRESH_ENDPOINT}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }).then(async (res) => {
        if (!res.ok) {
          if (await refusedAsEndedImpersonation(res)) {
            useAuthStore.getState().setImpersonationRevoked(true);
          } else if (res.status === 401) {
            // The session is over. Only the store tells `AuthGuard` so: left
            // signed in, the page stays up with every request refused and
            // nothing sends the person to sign in again until a full reload.
            // A rate limit or a 5xx is not a verdict on the session.
            useAuthStore.getState().logout();
          }
          return false;
        }
        markRefreshed();
        try {
          const data = (await res.json()) as { access_token?: string };
          if (data?.access_token) {
            // Keep the in-memory token (used for WS auth) in sync.
            useAuthStore.getState().setAccessToken(data.access_token);
          }
        } catch {
          // Body wasn't JSON - cookies were still rotated, treat as success.
        }
        return true;
      });
    })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

class ApiClient {
  private async send(
    endpoint: string,
    options: RequestOptions & { method: string },
  ): Promise<Response> {
    const { params, body, onProgress, ...fetchOptions } = options;

    let url = `/api${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams(params);
      url += `?${searchParams.toString()}`;
    }

    const activeOrgId = useOrgStore.getState().activeOrgId;

    // A FormData body carries its own multipart content type, boundary and all,
    // and is sent as-is. Anything else is JSON.
    const isMultipart = body instanceof FormData;

    const headers = {
      ...(isMultipart ? {} : { "Content-Type": "application/json" }),
      // The active organization travels on every request so org-scoped
      // endpoints resolve the same tenant the UI is showing. The server
      // verifies membership; an id the user does not belong to is refused,
      // and no header at all falls back to their personal org.
      ...(activeOrgId ? { "X-Organization-Id": activeOrgId } : {}),
      [CONSOLE_TAB_HEADER]: CONSOLE_TAB,
      ...fetchOptions.headers,
    };
    const payload = isMultipart ? (body as FormData) : body ? JSON.stringify(body) : undefined;

    // A fresh request each time, so the retry after a refresh reports its own
    // progress from zero.
    const doFetch = () =>
      onProgress
        ? sendWithProgress(
            url,
            {
              method: fetchOptions.method,
              headers,
              body: payload ?? null,
              signal: fetchOptions.signal,
            },
            onProgress,
          )
        : fetch(url, { ...fetchOptions, headers, body: payload });

    let response = await (SERVER_REFRESHING.has(endpoint) ? withAuthLock(doFetch) : doFetch());

    let retriedAfterRefresh = false;

    // Transparent 401 recovery: refresh once, then retry the request once.
    // Never on an endpoint whose 401 is the answer rather than an expired token,
    // and only a single time per call.
    if (response.status === 401 && !NO_REFRESH_RETRY.has(endpoint.split("?", 1)[0] ?? endpoint)) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        retriedAfterRefresh = true;
        response = await doFetch();
      }
    }

    if (!response.ok) {
      let errorData: unknown;
      try {
        errorData = await response.json();
      } catch {
        errorData = null;
      }
      if (response.status === 401 && retriedAfterRefresh) {
        // A recent refresh is only a reason to retry, not proof the session
        // still exists. Tell AuthGuard when the refreshed cookies are refused.
        if (
          typeof errorData === "object" &&
          errorData !== null &&
          "code" in errorData &&
          errorData.code === "IMPERSONATION_ENDED"
        ) {
          useAuthStore.getState().setImpersonationRevoked(true);
        } else {
          useAuthStore.getState().logout();
        }
      }
      throw new ApiError(response.status, parseErrorMessage(errorData), errorData);
    }

    return response;
  }

  private async request<T>(
    endpoint: string,
    options: RequestOptions & { method: string },
  ): Promise<T> {
    const response = await this.send(endpoint, options);

    const text = await response.text();
    if (!text) {
      return null as T;
    }

    return JSON.parse(text);
  }

  /**
   * The `Response` itself, for a body that is not JSON.
   *
   * A download and a preview want bytes, or text, or the `Content-Type` the
   * server chose - none of which survive `JSON.parse`. They were written as
   * bare `fetch` calls for that reason, and a bare `fetch` sends no
   * `X-Organization-Id`: on an org-scoped endpoint the backend then falls back
   * to the caller's personal organization, so a knowledge base belonging to the
   * organization on screen was fetched from a different tenant entirely.
   *
   * Everything `request` does except the parse - the organization header, the
   * one-shot 401 refresh, `ApiError` on a failure - so a caller reaching for
   * bytes does not have to give the rest up.
   */
  raw(endpoint: string, options?: RequestOptions) {
    return this.send(endpoint, { ...options, method: options?.method ?? "GET" });
  }

  get<T>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "GET" });
  }

  post<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "POST", body });
  }

  put<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "PUT", body });
  }

  patch<T>(endpoint: string, body?: unknown, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "PATCH", body });
  }

  delete<T>(endpoint: string, options?: RequestOptions) {
    return this.request<T>(endpoint, { ...options, method: "DELETE" });
  }

  /**
   * POST several files as one multipart body, naming each.
   *
   * The name matters: a folder upload carries `webkitRelativePath`, and that
   * path *is* the resource's name on the other side. Appending the bare `File`
   * would send only the basename, and a folder would arrive flattened with
   * every collision silently resolved by whichever file went last.
   */
  uploadMany<T>(endpoint: string, files: File[], nameOf: (file: File) => string) {
    const form = new FormData();
    for (const file of files) form.append("files", file, nameOf(file));
    return this.request<T>(endpoint, { method: "POST", body: form });
  }

  /**
   * POST a file as multipart, through the same proxy as everything else.
   *
   * `Content-Type` is deliberately absent: only the browser knows the multipart
   * boundary it generated, and setting the header by hand drops it - FastAPI
   * then rejects a body it was just handed. Going through `request` rather than
   * a bare `fetch` is what keeps the active organization header on an
   * org-scoped upload, and the 401-refresh with it.
   *
   * A `File` is sent as the form's `file` field; a form with other fields
   * beside it is built by the caller and sent as it is. `onProgress` reports
   * how much of it has gone up.
   */
  upload<T>(endpoint: string, file: File | FormData, options?: RequestOptions) {
    let form = file;
    if (file instanceof File) {
      form = new FormData();
      form.append("file", file);
    }
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: form,
    });
  }
}

export const apiClient = new ApiClient();
