import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  try {
    const data = await backendFetch<{ items: unknown[]; total: number }>(
      "/api/v1/me/mcp-connections",
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

export async function POST(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<unknown>("/api/v1/me/mcp-connections", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
