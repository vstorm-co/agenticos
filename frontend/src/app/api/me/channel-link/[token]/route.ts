import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";

/**
 * The chat account a link URL is about, and the confirmation that claims it.
 *
 * Same-origin so the session cookie authorises it: the token says which chat
 * account is on offer and the cookie says who is accepting, and only the second
 * can be trusted - the first arrived in a chat where anyone in the room could
 * have read it.
 */
export async function GET(request: NextRequest, context: { params: Promise<{ token: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { token } = await context.params;
  try {
    const data = await backendFetch<unknown>(
      `/api/v1/me/channel-link/${encodeURIComponent(token)}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function POST(request: NextRequest, context: { params: Promise<{ token: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { token } = await context.params;
  try {
    const data = await backendFetch<unknown>(
      `/api/v1/me/channel-link/${encodeURIComponent(token)}`,
      { method: "POST", headers: { Authorization: `Bearer ${accessToken}` } },
    );
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

/**
 * Disconnecting one chat account.
 *
 * The path segment is an identity id here rather than a link token - the two
 * never collide, because a token is only ever read by GET and POST, and a
 * DELETE addresses a row this person owns.
 */
export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ token: string }> },
) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { token } = await context.params;
  try {
    await backendFetch<null>(`/api/v1/me/channel-link/${encodeURIComponent(token)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
