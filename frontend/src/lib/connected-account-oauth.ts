import { randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

import { platformProxy } from "@/lib/platform-proxy";
import { ACCESS_TOKEN_COOKIE, secureCookies } from "@/lib/session-cookie";

export const ACCOUNT_OAUTH_COOKIE = `${ACCESS_TOKEN_COOKIE}_account_oauth`;
export const ACCOUNT_OAUTH_CALLBACK = "/api/me/mcp-connections/oauth/callback";

export async function startConnectedAccountOAuth(request: NextRequest): Promise<Response> {
  const text = await request.text();
  let options: unknown = {};
  if (text) {
    try {
      options = JSON.parse(text);
    } catch {
      return new NextResponse(null, { status: 400 });
    }
  }
  const supplied =
    typeof options === "object" && options !== null && !Array.isArray(options) ? options : {};
  const nonce = randomBytes(32).toString("base64url");
  const headers = new Headers(request.headers);
  headers.set("content-type", "application/json");
  headers.delete("content-length");
  const upstream = await platformProxy().POST(
    new NextRequest(request.url, {
      method: "POST",
      headers,
      body: JSON.stringify({ ...supplied, browser_nonce: nonce }),
    }),
  );
  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: upstream.headers,
  });
  if (upstream.ok) {
    response.cookies.set(ACCOUNT_OAUTH_COOKIE, nonce, {
      httpOnly: true,
      sameSite: "lax",
      secure: secureCookies(request),
      path: ACCOUNT_OAUTH_CALLBACK,
      maxAge: 600,
    });
  }
  return response;
}
