import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id } = await params;
    const data = await backendFetch(`/api/v1/orgs/${encodeURIComponent(id)}/invitations`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
    const { id } = await params;
    const body = await request.json();
    const data = await backendFetch(`/api/v1/orgs/${encodeURIComponent(id)}/invitations`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return bffJson(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
