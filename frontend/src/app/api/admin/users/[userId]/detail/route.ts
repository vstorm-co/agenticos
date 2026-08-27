import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

interface RouteParams {
  params: Promise<{ userId: string }>;
}

/** Where this person has access, when they were last here, what is still open. */
export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const { userId } = await params;
    const data = await backendFetch(`/api/v1/admin/users/${encodeURIComponent(userId)}/detail`, {
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
