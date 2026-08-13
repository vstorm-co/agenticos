import { NextRequest, NextResponse } from "next/server";
import { backendFetch, bffRefusal } from "@/lib/server-api";
import { isAppAdmin } from "@/lib/utils";

/**
 * The token behind an `/api/admin/*` route, or the refusal to answer with.
 *
 * A refusal is a `BFF_ERROR_KEYS` code, not a sentence: this runs outside the
 * `[locale]` segment, so there is no locale to resolve a message against, and
 * rendering it is the client's job (#603).
 */
export async function requireAdmin(
  request: NextRequest,
): Promise<{ error: NextResponse } | { accessToken: string }> {
  const accessToken = request.cookies.get("access_token")?.value;

  if (!accessToken) {
    return { error: bffRefusal("NOT_AUTHENTICATED", 401) };
  }

  try {
    const user = await backendFetch<{ is_app_admin?: boolean }>("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (!isAppAdmin(user)) {
      return { error: bffRefusal("FORBIDDEN", 403) };
    }

    return { accessToken };
  } catch {
    return { error: bffRefusal("NOT_AUTHENTICATED", 401) };
  }
}
