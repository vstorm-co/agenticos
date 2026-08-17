import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  const { id } = await params;
  try {
    const data = await backendFetch("/api/v1/org/integrations", {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Organization-Id": id,
      },
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  const { id } = await params;
  try {
    const body = await request.json();
    const data = await backendFetch("/api/v1/org/integrations", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "X-Organization-Id": id,
      },
      body: JSON.stringify(body),
    });
    return bffJson(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
