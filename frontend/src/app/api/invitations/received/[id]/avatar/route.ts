import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";
import { IMAGE_TYPES, baseContentType } from "@/lib/proxy-content-type";
import { ACCESS_TOKEN_COOKIE } from "@/lib/session-cookie";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id } = await params;
    const response = await fetch(
      `${BACKEND_URL}/api/v1/invitations/received/${encodeURIComponent(id)}/avatar`,
      {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      },
    );
    if (!response.ok) {
      return bffRefusal("AVATAR_NOT_AVAILABLE", response.status);
    }
    // Pinned to an image type, not echoed: served from the app's own origin under
    // a CSP that allows inline script, and the backend guesses this type from the
    // stored filename's suffix - so a stored `x.html` would be `text/html` here,
    // a script rather than a picture (#702). An unnamed type is refused too.
    const contentType = baseContentType(response.headers.get("content-type"));
    if (!IMAGE_TYPES.has(contentType)) {
      return bffRefusal("AVATAR_NOT_AVAILABLE", 502);
    }
    const buf = await response.arrayBuffer();
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
