import { NextRequest } from "next/server";

import { INVITATION_FLOW_PARAM, isInvitationFlow, stageCookieName } from "@/lib/invitation-links";
import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";
import { secureCookies } from "@/lib/session-cookie";
import type { LoginResponse } from "@/types";

/**
 * Sign in with a directory (LDAP) account's username and password.
 *
 * The same session the password login makes, and set the same way: both tokens
 * in HttpOnly cookies, the access token echoed in the body for the chat socket.
 * What differs is the body the backend reads - JSON with a `username`, because
 * this is not the OAuth2 password form - and the staged invitation: a directory
 * account is created on its first sign-in, under the deployment's sign-up policy,
 * so an invitee's httpOnly handle (#1414) rides along exactly as it does on the
 * register and OAuth starts, read from the cookie of the flow the form names.
 *
 * A refusal is forwarded whole, as the register proxy does: every one that
 * matters here - credentials rejected, an account the directory cannot use, the
 * directory unreachable, the sign-up policy - is an `AppException` envelope
 * carrying a sentence written for the person at the form.
 */
export async function POST(request: NextRequest) {
  try {
    // Not validated here: the backend's schema is the one that refuses a bad
    // body, and a second copy of its rules in this hop would drift from it. Only
    // the two credentials are picked, so a handle can come from the cookie alone.
    const body = (await request.json()) as Record<string, unknown>;
    const flow = request.nextUrl.searchParams.get(INVITATION_FLOW_PARAM);
    const handle = isInvitationFlow(flow)
      ? request.cookies.get(stageCookieName(flow))?.value
      : undefined;

    const data = await backendFetch<LoginResponse>("/api/v1/auth/ldap/login", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify({
        username: body.username,
        password: body.password,
        ...(handle ? { invitation_handle: handle } : {}),
      }),
    });

    const user = await backendFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${data.access_token}` },
    });

    const response = bffJson({ user, access_token: data.access_token });
    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 15, // 15 minutes
      path: "/",
    });
    response.cookies.set("refresh_token", data.refresh_token, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      return bffJson(error.data ?? { code: "LOGIN_FAILED" }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
