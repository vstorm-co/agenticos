import { NextResponse, type NextRequest } from "next/server";

import { mcpOAuthConnected, mcpOAuthRefused, mcpOAuthUpstreamRefusal } from "@/lib/mcp-oauth";
import { backendFetch } from "@/lib/server-api";

/**
 * OAuth redirect target. The provider sends the user here with `code` + `state`
 * (or an `error`). We forward them to the backend's state-authenticated
 * callback, then bounce the browser back to the MCP servers page with a status
 * `useMcpOAuthOutcome` turns into a toast. No auth cookie is required - the
 * `state` token authenticates the exchange. It redirected to
 * `/settings/integrations` until #657, which is itself a redirect to this page -
 * a hop for nothing, and a docstring naming a page that no longer exists.
 */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const servers = (query: string) =>
    NextResponse.redirect(new URL(`/mcp-servers?${query}`, request.url));

  const providerError = params.get("error");
  if (providerError) {
    return servers(mcpOAuthUpstreamRefusal(params.get("error_description") ?? providerError));
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state) {
    return servers(mcpOAuthRefused("MISSING_AUTHORIZATION_CODE"));
  }

  try {
    const result = await backendFetch<{
      ok: boolean;
      connection_name: string | null;
      error: string | null;
    }>("/api/v1/me/mcp-connections/oauth/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    });
    if (!result.ok) {
      return servers(
        result.error
          ? mcpOAuthUpstreamRefusal(result.error)
          : mcpOAuthRefused("AUTHORIZATION_FAILED"),
      );
    }
    return servers(mcpOAuthConnected(result.connection_name ?? ""));
  } catch {
    return servers(mcpOAuthRefused("AUTHORIZATION_FAILED"));
  }
}
