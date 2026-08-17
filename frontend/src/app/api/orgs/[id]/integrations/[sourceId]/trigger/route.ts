import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

interface RouteParams {
  params: Promise<{ id: string; sourceId: string }>;
}

export async function POST(request: NextRequest, { params }: RouteParams) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  const { id, sourceId } = await params;
  try {
    const data = await backendFetch(`/api/v1/org/integrations/${sourceId}/trigger`, {
      method: "POST",
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
