import { NextRequest } from "next/server";

import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { secureCookies } from "@/lib/session-cookie";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

/**
 * Redeem a scanned pairing code into this device's session (#2097).
 *
 * The phone's own user agent is forwarded, so the session it opens is listed
 * under the phone rather than under this server's fetch. The cookies are set the
 * way the OAuth return sets them; the access token is echoed for the chat socket.
 */
export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as { code?: unknown };
    if (typeof body.code !== "string" || !body.code) {
      return bffRefusal("MISSING_AUTHORIZATION_CODE", 400);
    }
    const tokens = await backendFetch<TokenPair>("/api/v1/auth/pairing-codes/redeem", {
      method: "POST",
      body: JSON.stringify({ code: body.code }),
      headers: {
        ...forwardedFor(request),
        "User-Agent": request.headers.get("user-agent") ?? "",
      },
    });
    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });
    const response = bffJson({ user, access_token: tokens.access_token });
    const options = {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      path: "/",
    } as const;
    response.cookies.set("access_token", tokens.access_token, { ...options, maxAge: 60 * 15 });
    response.cookies.set("refresh_token", tokens.refresh_token, {
      ...options,
      maxAge: 60 * 60 * 24 * 7,
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffRefusal("LOGIN_FAILED", error.status);
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
