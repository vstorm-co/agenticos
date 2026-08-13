import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError, backendErrorDetail } from "@/lib/server-api";
import { requireAdmin } from "@/lib/admin-auth";

export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    // An allowlist rather than the whole search string, so a parameter the
    // backend does not accept cannot 422 the page - the same shape the sibling
    // conversations proxy uses, and every key here is one `list_users` in
    // `admin_users.py` declares. `sort_by` and `sort_dir` were missing, so the
    // users table sent them, the proxy dropped them, and the backend fell back
    // to `created_at desc` under an arrow the screen had just flipped.
    const searchParams = request.nextUrl.searchParams;
    const params = new URLSearchParams();
    const forward = ["skip", "limit", "search", "sort_by", "sort_dir"];
    for (const key of forward) {
      const v = searchParams.get(key);
      if (v) params.set(key, v);
    }

    const qs = params.toString();
    const data = await backendFetch(`/api/v1/admin/users${qs ? `?${qs}` : ""}`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: backendErrorDetail(error) }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
