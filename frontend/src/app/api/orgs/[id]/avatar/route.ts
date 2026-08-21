import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";
import { IMAGE_TYPES, baseContentType } from "@/lib/proxy-content-type";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id } = await params;
    const formData = await request.formData();
    const response = await fetch(`${BACKEND_URL}/api/v1/orgs/${encodeURIComponent(id)}/avatar`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      body: formData,
    });
    const text = await response.text();
    return new NextResponse(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") || "application/json" },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id } = await params;
    const response = await fetch(`${BACKEND_URL}/api/v1/orgs/${encodeURIComponent(id)}/avatar`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
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
        "Cache-Control": "private, max-age=30",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
