import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch } from "@/lib/server-api";

/**
 * The chat accounts the signed-in person has connected.
 *
 * A link is granted in a chat and spent in a browser, so without this listing
 * the only record of what somebody connected is a message that has scrolled
 * away - and unlinking would have nowhere to live.
 */
export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  try {
    const data = await backendFetch<unknown>("/api/v1/me/channel-link", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
