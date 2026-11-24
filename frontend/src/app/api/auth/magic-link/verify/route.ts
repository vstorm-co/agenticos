import { type NextRequest } from "next/server";

import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, secureCookies } from "@/lib/session-cookie";
import type { MfaRequiredResponse } from "@/types";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  /** Where the link was minted to land. Signed into the token, so it cannot
      have been edited between the email and here; still judged again by
      `postSignInDestination` at the landing (#1214). */
  return_to?: string | null;
}

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<TokenResponse | MfaRequiredResponse>(
      "/api/v1/auth/magic-link/verify",
      {
        method: "POST",
        headers: { ...forwardedFor(request) },
        body: JSON.stringify(body),
      },
    );

    // An account with a second factor enabled stops here: the challenge
    // passes through untouched - no session, no cookies - carrying the
    // link's destination with it, and the page completes it at
    // `/auth/mfa/verify`.
    if ("mfa_required" in data) return bffJson(data);

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });

    const response = bffJson({
      user,
      access_token: data.access_token,
      return_to: data.return_to ?? null,
    });
    response.cookies.set(ACCESS_TOKEN_COOKIE, data.access_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 15,
      path: "/",
    });
    response.cookies.set(REFRESH_TOKEN_COOKIE, data.refresh_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
