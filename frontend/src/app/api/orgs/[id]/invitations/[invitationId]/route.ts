import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string; invitationId: string }>;
}

/**
 * Revoke a pending invitation as an administrator.
 *
 * By id, not by token. `/api/invitations/<token>` also revokes, but that route
 * belongs to the invitee - the token is the only thing they have. An admin
 * working from the members list has the id, and sending a live bearer
 * credential through a URL would only put it in access logs and history.
 */
export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id, invitationId } = await params;
    await backendFetch(
      `/api/v1/orgs/${encodeURIComponent(id)}/invitations/${encodeURIComponent(invitationId)}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      },
    );
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
