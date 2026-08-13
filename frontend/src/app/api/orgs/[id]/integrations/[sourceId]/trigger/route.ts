import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, backendErrorDetail } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string; sourceId: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  const { id, sourceId } = await params;
  try {
    const data = await backendFetch(`/api/v1/org/integrations/${sourceId}/trigger`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Organization-Id": id,
      },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError)
      return NextResponse.json({ detail: backendErrorDetail(error) }, { status: error.status });
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
