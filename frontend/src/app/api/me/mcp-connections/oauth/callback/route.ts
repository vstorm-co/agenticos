import { NextResponse, type NextRequest } from "next/server";

import {
  MCP_OAUTH_RETURN_COOKIE,
  mcpOAuthConnected,
  mcpOAuthRefused,
  mcpOAuthUpstreamRefusal,
  safeMcpOAuthReturn,
} from "@/lib/mcp-oauth";
import { ACCOUNT_OAUTH_COOKIE, ACCOUNT_OAUTH_CALLBACK } from "@/lib/connected-account-oauth";
import { ROUTES } from "@/lib/constants";
import { ACCESS_TOKEN_COOKIE } from "@/lib/session-cookie";
import { backendFetch } from "@/lib/server-api";

/**
 * OAuth redirect target. The provider sends the user here with `code` + `state`
 * (or an `error`). We forward them to the backend's state-authenticated
 * callback, then bounce the browser back to the MCP servers page - or to the
 * page that started the consent, where it remembered one in
 * `MCP_OAUTH_RETURN_COOKIE`; a chat that sent somebody to connect their Notion
 * gets them back to the conversation - with a status `useMcpOAuthOutcome` turns
 * into a toast. MCP uses state-only authentication; connected accounts also
 * forward the initiating session and browser nonce. Refusals go through
 * `@/lib/mcp-oauth` because this address accepts provider-controlled errors.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const back = safeMcpOAuthReturn(
    request.cookies.get(MCP_OAUTH_RETURN_COOKIE)?.value,
    request.nextUrl.origin,
  );
  const servers = (query: string) => {
    const target = back ?? ROUTES.CONNECTORS;
    // **A relative `Location`, resolved by the browser against the URL it asked
    // for.** `NextResponse.redirect` takes an absolute one, and the only origin
    // this process knows is the address it binds to - `HOSTNAME=0.0.0.0` and
    // `PORT=3000` in the Dockerfile - so behind a proxy every provider sent
    // somebody back to `http://0.0.0.0:3000/mcp-servers`, having authorized
    // successfully. Trusting `x-forwarded-host` would be the other answer and a
    // worse one: it is a header, and this address is reachable by strangers
    // (#1528).
    const response = new NextResponse(null, {
      status: 307,
      headers: { Location: `${target}${target.includes("?") ? "&" : "?"}${query}` },
    });
    // One consent, one return: a stale cookie must not steer the next.
    response.cookies.delete(MCP_OAUTH_RETURN_COOKIE);
    response.cookies.set(ACCOUNT_OAUTH_COOKIE, "", { path: ACCOUNT_OAUTH_CALLBACK, maxAge: 0 });
    return response;
  };

  const providerError = params.get("error");
  if (providerError) {
    return servers(mcpOAuthUpstreamRefusal(params.get("error_description") ?? providerError));
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    return servers(mcpOAuthRefused("MISSING_AUTHORIZATION_CODE"));
  }

  const nonce = request.cookies.get(ACCOUNT_OAUTH_COOKIE)?.value;
  const accessToken = nonce ? request.cookies.get(ACCESS_TOKEN_COOKIE)?.value : undefined;
  try {
    const result = await backendFetch<{
      ok: boolean;
      connection_name: string | null;
      connection_id: string | null;
      scope: "user" | "org" | null;
      error: string | null;
    }>("/api/v1/me/mcp-connections/oauth/callback", {
      method: "POST",
      ...(accessToken ? { headers: { Authorization: `Bearer ${accessToken}` } } : {}),
      body: JSON.stringify({
        code,
        state,
        browser_nonce: nonce,
      }),
    });
    if (!result.ok) {
      return servers(
        result.error
          ? mcpOAuthUpstreamRefusal(result.error)
          : mcpOAuthRefused("AUTHORIZATION_FAILED"),
      );
    }
    // The id only for the organization's: that is the account an agent binds,
    // so its return offers "Add to an agent" (#2075).
    return servers(
      mcpOAuthConnected(
        result.connection_name ?? "",
        result.scope === "org" ? result.connection_id : null,
      ),
    );
  } catch {
    return servers(mcpOAuthRefused("AUTHORIZATION_FAILED"));
  }
}
