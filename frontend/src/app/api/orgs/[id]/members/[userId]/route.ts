import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string; userId: string }>;
}

export async function PATCH(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id, userId } = await params;
    const body = await request.json();
    const data = await backendFetch(`/api/v1/orgs/${id}/members/${userId}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError)
      return NextResponse.json({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id, userId } = await params;
    await backendFetch(`/api/v1/orgs/${id}/members/${userId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError)
      return NextResponse.json({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
