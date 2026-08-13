import { NextRequest, NextResponse } from "next/server";
import { bffRefusal } from "@/lib/server-api";

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
    const buf = await response.arrayBuffer();
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": response.headers.get("content-type") || "image/jpeg",
        "Cache-Control": "private, max-age=30",
      },
    });
  } catch {
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
