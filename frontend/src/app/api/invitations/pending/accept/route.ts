import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal, forwardedFor } from "@/lib/server-api";
import { INVITATION_FLOW_PARAM, isInvitationFlow, stageCookieName } from "@/lib/invitation-links";

/**
 * Close a staged invitation once the invitee has signed in (#1414).
 *
 * The pending landing names its flow in `?flow=`, and the handle rides the `httpOnly`
 * cookie of that name, which this route reads and the browser cannot. It is forwarded
 * to the backend in a header, redeemed there exactly once, and the invitation accepted
 * as the caller - with the caller's own address forwarded, since the backend rate
 * limits this per IP and would otherwise count every invitee against the frontend
 * container.
 *
 * The cookie is cleared once the redeem has run - on success and on an invitation-level
 * refusal - because the handle is then spent and a stale cookie would only mislead.
 * It is kept wherever the redeem may not have run: a 401 (the session is rejected
 * first), a 429 (the rate limit runs before the redeem, so the handle is unspent and
 * the advertised retry needs it), and a 5xx or an unreachable backend, where nothing
 * says which side of the redeem the failure fell on and a retry answering a miss is
 * cheaper than an invitation lost.
 */
function handleIsSpent(status: number): boolean {
  return status >= 400 && status < 500 && status !== 401 && status !== 429;
}

export async function POST(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);

  const flow = request.nextUrl.searchParams.get(INVITATION_FLOW_PARAM);
  if (!isInvitationFlow(flow)) return bffRefusal("INVITATION_NOT_FOUND", 404);
  const cookieName = stageCookieName(flow);
  const handle = request.cookies.get(cookieName)?.value;
  if (!handle) return bffRefusal("INVITATION_NOT_FOUND", 404);

  try {
    await backendFetch("/api/v1/invitations/staged/accept", {
      method: "POST",
      headers: {
        ...forwardedFor(request),
        Authorization: `Bearer ${accessToken}`,
        "X-Invitation-Handle": handle,
      },
    });
    const response = new NextResponse(null, { status: 204 });
    response.cookies.delete(cookieName);
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const response = bffJson({ detail: error.message }, { status: error.status });
      if (handleIsSpent(error.status)) response.cookies.delete(cookieName);
      return response;
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
