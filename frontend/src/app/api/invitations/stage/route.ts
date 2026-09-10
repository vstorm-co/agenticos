import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal, forwardedFor } from "@/lib/server-api";
import { secureCookies } from "@/lib/session-cookie";

/**
 * Stage an invitation deep link before the sign-in round trip (#1414).
 *
 * The token arrives from the browser once, here, and never leaves: the backend
 * stores it under an opaque handle, which this route sets as an `httpOnly` cookie
 * the browser cannot read. The reply carries nothing but success, so the raw token
 * is not in a response a script sees, in the URL, or in `sessionStorage`. The
 * cookie's lifetime matches the handle's server-side, so neither outlives the other.
 */
const STAGE_COOKIE = "invitation_stage";
const STAGE_TTL_SECONDS = 1800;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { handle } = await backendFetch<{ handle: string }>("/api/v1/invitations/stage", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify({ token: body?.token }),
    });

    const response = bffJson({ staged: true });
    response.cookies.set(STAGE_COOKIE, handle, {
      httpOnly: true,
      secure: secureCookies(request),
      sameSite: "lax",
      maxAge: STAGE_TTL_SECONDS,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
