import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const searchParams = request.nextUrl.searchParams;
    const skip = searchParams.get("skip") || "0";
    const limit = searchParams.get("limit") || "50";
    const ratingFilter = searchParams.get("rating_filter");
    const withCommentsOnly = searchParams.get("with_comments_only") === "true";

    let url = `/api/v1/admin/ratings?skip=${skip}&limit=${limit}`;
    if (ratingFilter) url += `&rating_filter=${encodeURIComponent(ratingFilter)}`;
    if (withCommentsOnly) url += `&with_comments_only=true`;

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
