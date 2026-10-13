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
    const data = await backendFetch<{ access_token: string; refresh_token: string }>(
      "/api/v1/auth/password/change",
      {
        method: "POST",
        headers: { ...authHeaders, ...forwardedFor(request) },
        body: JSON.stringify(body),
      },
    );
    // The change revoked every session including this device's, so the backend
    // returns a fresh pair at the new credential version; the cookies are swapped
    // to it, or the next refresh - now on the old version - would 401 (#1517).
    const response = bffJson({ access_token: data.access_token });
    response.cookies.set("access_token", data.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 15,
      path: "/",
    });
    response.cookies.set("refresh_token", data.refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return response;
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
