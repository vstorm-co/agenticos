import { NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

/**
 * The announcement banner, for a signed-in user.
 *
 * Behind a session, unlike the rest of `/api/branding`: an announcement is an
 * operator talking to the people using the deployment - an upgrade window, who to
 * ping - and a stranger on the sign-in page has no part in it. The backend gates
 * it too; this is the cookie being turned into the bearer token that gate reads.
 */
export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) return bffRefusal("NOT_AUTHENTICATED", 401);
  try {
    const data = await backendFetch<unknown>("/api/v1/branding/notice", {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
