import { type NextRequest } from "next/server";

import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";

/**
 * Unauthenticated, like the password-reset and magic-link confirmations beside
 * it: the link is followed from the *new* address, routinely in a browser that
 * has never signed in, and the token is the whole of the proof (#1772).
 */
export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<unknown>("/api/v1/auth/email-change/confirm", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify(body),
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
