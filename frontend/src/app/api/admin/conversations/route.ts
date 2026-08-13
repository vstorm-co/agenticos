import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    // Forward query params to the backend's admin router, which answers
    // AdminConversationList with user_email and filters on user_id. There used to
    // be a second endpoint doing a worse version of this - it is gone.
    //
    // An allowlist rather than the whole search string, so a parameter the
    // backend does not accept cannot 422 the page. Which is also its failure
    // mode: `agent_id` was missing from this list, so the screen's agent filter
    // sent a value that never left the proxy and the table answered with every
    // thread instead. `admin-routes.test.ts` pins each one the screen can send.
    const searchParams = request.nextUrl.searchParams;
    const params = new URLSearchParams();
    const forward = [
      "skip",
      "limit",
      "search",
      "user_id",
      "agent_id",
      "status",
      "sort_by",
      "sort_dir",
    ];
    for (const key of forward) {
      const v = searchParams.get(key);
      if (v) params.set(key, v);
    }

    const qs = params.toString();
    const url = `/api/v1/admin/conversations${qs ? `?${qs}` : ""}`;

    const data = await backendFetch(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
