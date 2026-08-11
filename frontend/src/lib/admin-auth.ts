import { NextRequest, NextResponse } from "next/server";
import { backendFetch } from "@/lib/server-api";
import { isAppAdmin } from "@/lib/utils";

/**
 * The token behind an `/api/admin/*` route, or the refusal to answer with.
 *
 * Each `detail` is a wire payload, not copy: this runs outside the `[locale]`
 * segment, so there is no locale to resolve a message against, and rendering it
 * is the client's job (#603).
 */
export async function requireAdmin(
  request: NextRequest,
): Promise<{ error: NextResponse } | { accessToken: string }> {
  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    return {
      // i18n-exempt: a wire payload from a route with no locale in scope - see above.
      error: NextResponse.json({ detail: "Not authenticated" }, { status: 401 }),
    };
  }

  try {
    const user = await backendFetch<{ is_app_admin?: boolean }>("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!isAppAdmin(user)) {
      return {
        error: NextResponse.json({ detail: "Forbidden" }, { status: 403 }),
      };
    }

    return { accessToken };
  } catch {
    return {
      // i18n-exempt: a wire payload from a route with no locale in scope - see above.
      error: NextResponse.json({ detail: "Not authenticated" }, { status: 401 }),
    };
  }
}
