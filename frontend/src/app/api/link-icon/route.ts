import { NextRequest } from "next/server";

import { proxyLinkIcon } from "@/lib/link-icon-proxy";
import { ACCESS_TOKEN_COOKIE } from "@/lib/session-cookie";

export async function GET(request: NextRequest): Promise<Response> {
  if (!request.cookies.get(ACCESS_TOKEN_COOKIE)?.value) return new Response(null, { status: 401 });
  return proxyLinkIcon(request.nextUrl.searchParams.get("host"));
}
