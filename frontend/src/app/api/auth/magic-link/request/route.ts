import { type NextRequest } from "next/server";

import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";

export async function POST(request: NextRequest) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const data = await backendFetch<unknown>("/api/v1/auth/magic-link/request", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffJson({ detail: error.message }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
