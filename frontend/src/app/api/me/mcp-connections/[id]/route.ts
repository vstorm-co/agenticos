import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

export async function PATCH(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { id } = await context.params;
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<unknown>(
      `/api/v1/me/mcp-connections/${encodeURIComponent(id)}`,
      {
        method: "PATCH",
        body: JSON.stringify(body),
        headers: { Authorization: `Bearer ${accessToken}` },
      },
    );
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  const { id } = await context.params;
  try {
    await backendFetch<null>(`/api/v1/me/mcp-connections/${encodeURIComponent(id)}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
