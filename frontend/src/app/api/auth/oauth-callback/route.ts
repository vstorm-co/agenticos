import { NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, secureCookies } from "@/lib/session-cookie";

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export async function POST(request: NextRequest) {
  try {
    const body: unknown = await request.json();
    if (
      typeof body !== "object" ||
      body === null ||
      !("code" in body) ||
      typeof body.code !== "string" ||
      !body.code ||
      body.code.length > 1024
    ) {
      return bffRefusal("MISSING_AUTHORIZATION_CODE", 400);
    }

    const verifier = "code_verifier" in body ? body.code_verifier : undefined;
    if (
      verifier !== undefined &&
      (typeof verifier !== "string" || !/^[A-Za-z0-9._~-]{43,128}$/.test(verifier))
    ) {
      return bffRefusal("LOGIN_FAILED", 400);
    }
    const tokens = await backendFetch<TokenPair>("/api/v1/oauth/exchange", {
      method: "POST",
      body: JSON.stringify({
        code: body.code,
        ...(verifier === undefined ? {} : { code_verifier: verifier }),
      }),
    });

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });

    const response = bffJson({
      user,
      access_token: tokens.access_token,
    });
    response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 15,
      path: "/",
    });
    response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = (error.data as { detail?: string })?.detail;
      if (!detail) return bffRefusal("LOGIN_FAILED", error.status);
      return bffJson({ detail }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
