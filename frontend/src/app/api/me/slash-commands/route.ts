import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  try {
    const data = await backendFetch<{ items: unknown[]; total: number }>(
      "/api/v1/me/slash-commands",
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
