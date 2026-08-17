import { BackendApiError, backendFetch, bffJson, bffRefusal } from "@/lib/server-api";
import type { HealthResponse } from "@/types";

export async function GET() {
  try {
    const data = await backendFetch<HealthResponse>("/api/v1/health");
    return bffJson(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return bffRefusal("BACKEND_UNAVAILABLE", error.status);
    }
    return bffRefusal("INTERNAL_SERVER_ERROR", 500);
  }
}
