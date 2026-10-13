import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal, forwardedFor } from "@/lib/server-api";
import { stageCookieName } from "@/lib/invitation-links";
import { secureCookies } from "@/lib/session-cookie";

/**
 * Stage an invitation deep link before the sign-in round trip (#1414).
 *
 * The token arrives from the browser once, here, and never leaves: the backend
 * stores it under an opaque handle, which this route sets as an `httpOnly` cookie
 * the browser cannot read. The reply carries the flow id and nothing else, so the
 * raw token is not in a response a script sees, in the URL, or in `sessionStorage`.
 * The cookie's lifetime matches the handle's server-side, so neither outlives the
 * other.
 *
 * The cookie is named for the flow rather than fixed, because a fixed name is one
 * slot: two invitation links opened side by side while signed out each staged into
 * it, the second overwriting the first, and both pending tabs then redeemed the
 * second. Each staging mints its own id, the pending landing carries it, and the
 * accept reads exactly the cookie that id names.
 */
const STAGE_TTL_SECONDS = 1800;

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { handle } = await backendFetch<{ handle: string }>("/api/v1/invitations/stage", {
      method: "POST",
      headers: { ...forwardedFor(request) },
      body: JSON.stringify({ token: body?.token }),
    });

    const flow = crypto.randomUUID().replaceAll("-", "");
    const response = bffJson({ staged: true, flow });
    response.cookies.set(stageCookieName(flow), handle, {
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
