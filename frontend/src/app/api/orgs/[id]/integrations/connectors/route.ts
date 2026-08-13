import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  const { id } = await params;
  try {
    const data = await backendFetch("/api/v1/org/integrations/connectors", {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Organization-Id": id,
      },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError)
      return NextResponse.json({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
