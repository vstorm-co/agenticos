import { NextResponse, type NextRequest } from "next/server";

import { BackendApiError, backendFetch, backendErrorDetail } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  try {
    const data = await backendFetch<{ items: unknown[]; total: number }>(
      "/api/v1/me/slash-commands",
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: backendErrorDetail(error) }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
