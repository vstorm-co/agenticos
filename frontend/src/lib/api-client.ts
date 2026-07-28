/**
 * Client-side API client.
 * All requests go through Next.js API routes (/api/*), never directly to the backend.
 * This keeps the backend URL hidden from the browser.
 */

import { ApiError, parseErrorMessage } from "@/lib/api-error";
import { useAuthStore, useOrgStore } from "@/stores";

// Re-exported because this module was where `ApiError` lived and where the rest
// of the app still imports it from. Its definition moved to `api-error.ts` so
// that reading a refusal does not require pulling in the fetch client.
export { ApiError };

interface RequestOptions extends Omit<RequestInit, "body"> {
  params?: Record<string, string>;
  body?: unknown;
}

// The proxy route that mints a fresh access token from the refresh cookie.
const REFRESH_ENDPOINT = "/auth/refresh";

// Shared in-flight refresh promise so a burst of concurrent 401s triggers only
// ONE refresh round-trip. Reset once the refresh settles.
let refreshPromise: Promise<boolean> | null = null;

/**
 * Attempt a single token refresh, de-duplicating concurrent callers.
 * Resolves true on success (cookies + in-memory access token updated), false
 * if the refresh itself failed (caller should surface the original 401).
 */
function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch(`/api${REFRESH_ENDPOINT}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
      .then(async (res) => {
        if (!res.ok) return false;
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
      })
      .catch(() => false)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

class ApiClient {
  private async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const { params, body, ...fetchOptions } = options;

    let url = `/api${endpoint}`;

    if (params) {
      const searchParams = new URLSearchParams(params);
      url += `?${searchParams.toString()}`;
    }

    const activeOrgId = useOrgStore.getState().activeOrgId;

    // A FormData body carries its own multipart content type, boundary and all,
    // and is sent as-is. Anything else is JSON.
    const isMultipart = body instanceof FormData;

    const doFetch = () =>
      fetch(url, {
        ...fetchOptions,
        headers: {
          ...(isMultipart ? {} : { "Content-Type": "application/json" }),
          // The active organization travels on every request so org-scoped
          // endpoints resolve the same tenant the UI is showing. The server
          // verifies membership; an id the user does not belong to is refused,
          // and no header at all falls back to their personal org.
          ...(activeOrgId ? { "X-Organization-Id": activeOrgId } : {}),
          ...fetchOptions.headers,
        },
        body: isMultipart ? (body as FormData) : body ? JSON.stringify(body) : undefined,
      });

    let response = await doFetch();

    // Transparent 401 recovery: refresh once, then retry the request once.
    // Never recurse into the refresh endpoint itself (would loop), and only
    // attempt this a single time per call.
    if (response.status === 401 && endpoint !== REFRESH_ENDPOINT) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
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
      throw new ApiError(response.status, parseErrorMessage(errorData), errorData);
    }

    // Handle empty responses
    const text = await response.text();
    if (!text) {
      return null as T;
    }

    return JSON.parse(text);
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
   */
  upload<T>(endpoint: string, file: File, options?: RequestOptions) {
    const form = new FormData();
    form.append("file", file);
    return this.request<T>(endpoint, {
      ...options,
      method: "POST",
      body: form,
    });
  }
}

export const apiClient = new ApiClient();
