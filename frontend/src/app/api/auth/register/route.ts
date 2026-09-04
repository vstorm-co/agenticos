import { NextRequest } from "next/server";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import type { RegisterResponse } from "@/types";

/**
 * Create an account.
 *
 * The body is forwarded whole, which is how `invitation_token` reaches the sign-up
 * policy without this route knowing about it.
 *
 * A refusal is forwarded whole too, and that is the part worth saying. This used to
 * read `detail` off the backend's body and fall back to a generic
 * `REGISTRATION_FAILED` when there was none - and every refusal that matters here is
 * an `AppException`, which answers `{"error": {...}}` and carries no `detail`. So
 * "this deployment is invite-only", "that email domain cannot register" and "ask an
 * administrator for an account" all reached the form as "registration failed", which
 * tells somebody nothing about a rule they could satisfy. `getErrorMessage` reads the
 * envelope; passing it through is all that was needed.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const data = await backendFetch<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify(body),
    });

    return bffJson(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffJson(error.data ?? { code: "REGISTRATION_FAILED" }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
