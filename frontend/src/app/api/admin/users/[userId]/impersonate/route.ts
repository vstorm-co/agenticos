import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

interface RouteParams {
  params: Promise<{ userId: string }>;
}

interface ImpersonateResponse {
  access_token: string;
  token_type: string;
  impersonated_user_id: string;
  impersonated_by: string;
  expires_in: number;
  expires_at: string;
  session_id: string;
}

/**
 * Start acting as a user - by swapping the browser's own access cookie, not by
 * handing the token back.
 *
 * The token goes where every other access token lives, an HttpOnly cookie, and
 * reaches the page only the way every access token does - echoed by
 * `/api/auth/me` for the chat socket. Never into a response body a page could
 * put on the operating system clipboard, where it would outlive the tab and be
 * readable by whatever the operator pasted into next (#1044). The refresh
 * cookie is left alone on purpose: it is the administrator's own, and it is
 * what the next `/api/auth/me` refreshes from once the impersonation has ended
 * or expired - so ending one is clearing this cookie, and the administrator is
 * themselves again on the next request without signing in.
 *
 * The cookie outlives the token by a few minutes on purpose. A cookie that
 * lapsed with the token would leave the jar holding only the administrator's
 * refresh cookie, and a request refused at the boundary would be refreshed and
 * replayed as them; while the expired impersonation is still in the jar, the
 * refresh route sees what it is and refuses instead. A revocation before then
 * is the backend's to enforce: the token names its session row and is refused
 * the moment that row is ended.
 */
const COOKIE_GRACE_SECONDS = 5 * 60;

export async function POST(request: NextRequest, { params }: RouteParams) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const { userId } = await params;
    const { access_token, ...impersonation } = await backendFetch<ImpersonateResponse>(
      `/api/v1/admin/users/${encodeURIComponent(userId)}/impersonate`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      },
    );
    const response = bffJson(impersonation);
    response.cookies.set("access_token", access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: impersonation.expires_in + COOKIE_GRACE_SECONDS,
      path: "/",
    });
    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
