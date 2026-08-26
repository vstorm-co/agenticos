import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string; sourceId: string }>;
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  const { id, sourceId } = await params;
  try {
    await backendFetch<null>(`/api/v1/org/integrations/${encodeURIComponent(sourceId)}`, {
      method: "DELETE",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "X-Organization-Id": id,
      },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError)
      return bffJson({ detail: error.message }, { status: error.status });
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
