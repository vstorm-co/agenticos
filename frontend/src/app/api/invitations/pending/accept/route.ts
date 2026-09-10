import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

/**
 * Close a staged invitation once the invitee has signed in (#1414).
 *
 * The handle rides an `httpOnly` cookie this route reads and the browser cannot; it
 * is forwarded to the backend in a header, redeemed there exactly once, and the
 * invitation accepted as the caller. The cookie is cleared once the redeem has run -
 * on success and on an invitation-level refusal - because the handle is then spent
 * and a stale cookie would only mislead. It is kept on a 401: the session is rejected
 * before the redeem, so the handle is unspent, and the client's refresh-and-retry (or
 * a later valid session) can still close the invitation with it.
 */
const STAGE_COOKIE = "invitation_stage";

export async function POST(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);

  const handle = request.cookies.get(STAGE_COOKIE)?.value;
  if (!handle) return bffRefusal("INVITATION_NOT_FOUND", 404);

  try {
    await backendFetch("/api/v1/invitations/staged/accept", {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}`, "X-Invitation-Handle": handle },
    });
    const response = new NextResponse(null, { status: 204 });
    response.cookies.delete(STAGE_COOKIE);
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const response = bffJson({ detail: error.message }, { status: error.status });
      if (error.status !== 401) response.cookies.delete(STAGE_COOKIE);
      return response;
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
