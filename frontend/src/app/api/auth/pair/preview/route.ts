import { NextRequest } from "next/server";

import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import type { PairingIdentity } from "@/lib/pairing-api";

/** Read the scanned account identity without setting or replacing session cookies. */
export async function POST(request: NextRequest) {
  try {
    const body: unknown = await request.json();
    if (
      !body ||
      typeof body !== "object" ||
      !("code" in body) ||
      typeof body.code !== "string" ||
      !body.code
    ) {
      return bffRefusal("MISSING_AUTHORIZATION_CODE", 400);
    }
    return bffJson(
      await backendFetch<PairingIdentity>("/api/v1/auth/pairing-codes/preview", {
        method: "POST",
        body: JSON.stringify({ code: body.code }),
        headers: forwardedFor(request),
      }),
    );
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffRefusal("LOGIN_FAILED", error.status);
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
