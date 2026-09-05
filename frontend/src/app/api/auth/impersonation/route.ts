import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

/**
 * Refusals that mean the impersonation is over already, whatever ended it.
 *
 * 401 is the backend refusing the token because its session row is gone - ended
 * from another tab, revoked by the person signing out everywhere, or simply
 * expired. 400 is a cookie that is nobody acting as anybody. Neither is a reason
 * to keep the cookie: in both the right answer is to drop it and let the next
 * request refresh the administrator's own session.
 */
const ALREADY_OVER = new Set([400, 401]);

/**
 * End the impersonation this browser is running under.
 *
 * Two things, in order: tell the backend, so the session row is closed and the
 * end is audited, and then clear the access cookie the impersonation lives in.
 * The refresh cookie was never touched - it is the administrator's own - so the
 * next `/api/auth/me` mints them an access token as themselves (#1044).
 */
export async function DELETE(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;

  if (accessToken) {
    try {
      await backendFetch("/api/v1/auth/impersonation", {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
    } catch (error) {
      if (!(error instanceof BackendApiError)) {
        return bffRefusal("INTERNAL_SERVER_ERROR", 500);
      }
      if (!ALREADY_OVER.has(error.status)) {
        return bffJson({ detail: error.message }, { status: error.status });
      }
    }
  }

  const response = bffJson({ ok: true });
  response.cookies.set("access_token", "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    maxAge: 0,
    path: "/",
  });
  return response;
}
