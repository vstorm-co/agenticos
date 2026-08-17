import { NextRequest } from "next/server";

import { requireAdmin } from "@/lib/admin-auth";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const data = await backendFetch<unknown>(
      `/api/v1/admin/organizations${request.nextUrl.search}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
