import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    // One caller left: the admin user drawer's recent-threads list. The
    // deployment-wide browser this proxy was written for is gone, and with it
    // the search, sort and status parameters it sent - an allowlist that
    // forwards what nothing sends is a list nobody can read a contract out of.
    const searchParams = request.nextUrl.searchParams;
    const params = new URLSearchParams();
    for (const key of ["user_id", "skip", "limit"]) {
      const value = searchParams.get(key);
      if (value) params.set(key, value);
    }

    const qs = params.toString();
    const url = `/api/v1/admin/conversations${qs ? `?${qs}` : ""}`;

    const data = await backendFetch(url, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    });

    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
