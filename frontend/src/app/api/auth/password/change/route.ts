import { type NextRequest } from "next/server";

import {
  BackendApiError,
  backendFetch,
  bffJson,
  bffRefusal,
  forwardedFor,
  forwardRateLimit,
} from "@/lib/server-api";

export async function POST(request: NextRequest) {
  // The change is authenticated, so the access-token cookie is forwarded as a
  // bearer; with none, the backend refuses it as any signed-in route does.
  const accessToken = request.cookies.get("access_token")?.value;
  const authHeaders: Record<string, string> = accessToken
    ? { Authorization: `Bearer ${accessToken}` }
    : {};
  try {
    const body = (await request.json()) as Record<string, unknown>;
    await backendFetch<unknown>("/api/v1/auth/password/change", {
      method: "POST",
      headers: { ...authHeaders, ...forwardedFor(request) },
      body: JSON.stringify(body),
    });
    return new Response(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 429) return forwardRateLimit(error);
      // The backend's own error body, so "Current password is incorrect" reaches
      // the form rather than a generic message the field cannot act on.
      return bffJson(error.data, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
