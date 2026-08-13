import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";

export async function POST(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { id } = await context.params;
  try {
    const data = await backendFetch<unknown>(`/api/v1/me/mcp-connections/${id}/test`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
