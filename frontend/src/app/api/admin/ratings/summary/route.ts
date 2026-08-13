import { NextRequest, NextResponse } from "next/server";
import { BackendApiError, backendFetch, bffRefusal } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const searchParams = request.nextUrl.searchParams;
    const params = new URLSearchParams();
    const forward = ["from", "to"];
    for (const key of forward) {
      const v = searchParams.get(key);
      if (v) params.set(key, v);
    }

    const qs = params.toString();
    const data = await backendFetch(`/api/v1/admin/ratings/summary${qs ? `?${qs}` : ""}`, {
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
