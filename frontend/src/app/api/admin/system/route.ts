import { NextRequest, NextResponse } from "next/server";

import { requireAdmin } from "@/lib/admin-auth";
import { BackendApiError, backendFetch } from "@/lib/server-api";

/**
 * Per-service health for the admin system page.
 *
 * The page used to read `/health/ready`, which is the Kubernetes readiness probe
 * - unauthenticated, and therefore unable to say anything specific about the
 * deployment. This is the authenticated view, where a check may report which
 * pgvector version is installed and how much is configured.
 */
export async function GET(request: NextRequest) {
  try {
    const adminCheck = await requireAdmin(request);
    if ("error" in adminCheck) return adminCheck.error;
    const { accessToken } = adminCheck;

    const data = await backendFetch<unknown>("/api/v1/admin/system", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
