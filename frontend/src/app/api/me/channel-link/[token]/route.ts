import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch } from "@/lib/server-api";

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
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
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
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

export async function POST(request: NextRequest, context: { params: Promise<{ token: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
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
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
