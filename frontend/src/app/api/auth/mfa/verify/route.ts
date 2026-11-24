import { NextRequest } from "next/server";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE, secureCookies } from "@/lib/session-cookie";
import type { LoginResponse } from "@/types";

/**
 * Complete the second step of a sign-in: the challenge token from the
 * password step, plus the authenticator code.
 *
 * The session is set the same way the password login sets it: both tokens
 * in HttpOnly cookies, the access token echoed in the body for the chat
 * socket, and the link's destination - when the challenge came from a magic
 * link - carried through for the client to navigate to.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const data = await backendFetch<LoginResponse & { return_to?: string | null }>(
      "/api/v1/auth/mfa/verify",
      {
        method: "POST",
        redirect: "manual",
        headers: { ...forwardedFor(request) },
        body: JSON.stringify({ mfa_token: body.mfa_token, code: body.code }),
      },
    );

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });

    // Set HTTP-only cookies for tokens. Also return the access_token in the
    // body so the client can use it for cross-origin WebSocket auth.
    const response = bffJson({
      user,
      access_token: data.access_token,
      return_to: data.return_to ?? null,
    });

    response.cookies.set(ACCESS_TOKEN_COOKIE, data.access_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 15, // 15 minutes
      path: "/",
    });

    response.cookies.set(REFRESH_TOKEN_COOKIE, data.refresh_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: "/",
    });

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const desktopCallback = desktopCallbackFrom(error);
      if (desktopCallback) return bffJson({ desktop_callback_url: desktopCallback });
      if (error.status >= 300 && error.status < 400) return bffRefusal("LOGIN_FAILED", 502);
      if (error.status === 429) return forwardRateLimit(error);
      const detail = (error.data as { detail?: string })?.detail;
      if (!detail) return bffRefusal("LOGIN_FAILED", error.status);
      return bffJson({ detail }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

function desktopCallbackFrom(error: BackendApiError): string | null {
  if (error.status < 300 || error.status >= 400) return null;
  const location = error.headers?.get("location");
  if (!location) return null;
  try {
    const url = new URL(location);
    if (
      url.protocol !== "agenticos:" ||
      url.hostname !== "auth" ||
      url.pathname !== "/callback" ||
      !url.searchParams.get("code") ||
      !url.searchParams.has("desktop_nonce")
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}
