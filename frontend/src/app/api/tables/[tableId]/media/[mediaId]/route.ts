import { NextRequest } from "next/server";
import { platformProxy } from "@/lib/platform-proxy";

const proxy = platformProxy();

/** Image elements cannot send the organization header; table grants still apply. */
export function GET(request: NextRequest): Promise<Response> {
  const headers = new Headers(request.headers);
  const organization = request.nextUrl.searchParams.get("organization_id");
  if (organization) headers.set("X-Organization-Id", organization);
  return proxy.GET(new NextRequest(request, { headers }));
}
