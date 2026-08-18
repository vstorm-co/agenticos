import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

/**
 * The chat accounts the signed-in person has connected.
 *
 * A link is granted in a chat and spent in a browser, so without this listing
 * the only record of what somebody connected is a message that has scrolled
 * away - and unlinking would have nowhere to live.
 */
export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return bffRefusal("NOT_AUTHENTICATED", 401);
  }
  try {
    const data = await backendFetch<unknown>("/api/v1/me/channel-link", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
