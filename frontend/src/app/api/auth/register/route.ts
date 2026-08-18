import { NextRequest } from "next/server";
import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import type { RegisterResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const data = await backendFetch<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });

    return bffJson(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = (error.data as { detail?: string })?.detail;
      if (!detail) return bffRefusal("REGISTRATION_FAILED", error.status);
      return bffJson({ detail }, { status: error.status });
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
