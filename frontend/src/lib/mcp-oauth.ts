import type { Translate } from "@/lib/agent-step-captions";

/**
 * The query an MCP OAuth consent hands back to the page, from both ends.
 *
 * The provider redirects the browser to `/api/me/mcp-connections/oauth/callback`,
 * which has no way to answer the person - a JSON body on a page nobody navigated
 * to is a dead end - so every outcome ends as a redirect carrying its result in
 * the query string. That contract used to be spelled out in the route handler
 * alone and read by nothing (#657): a refused exchange landed on the MCP servers
 * page looking exactly like an accepted one. The writer and the reader live here
 * together so the next change to one is made in sight of the other.
 */

/** A refusal written in this repository, and therefore translatable. */
export type McpOAuthFailure = "AUTHORIZATION_FAILED" | "MISSING_AUTHORIZATION_CODE";

/** Copy for each, under the `mcp` namespace. */
const FAILURE_KEYS: Record<McpOAuthFailure, string> = {
  AUTHORIZATION_FAILED: "oauthFailed",
  MISSING_AUTHORIZATION_CODE: "oauthMissingCode",
};

/** Everything the redirect adds, so the reader can take it all back off again. */
export const MCP_OAUTH_PARAMS = ["mcp_oauth", "name", "reason"] as const;

export type McpOAuthOutcome =
  { status: "success"; name: string } | { status: "error"; reason: string };

/** The query for a consent that finished, naming the connection it created. */
export function mcpOAuthConnected(name: string): string {
  return `mcp_oauth=success&name=${encodeURIComponent(name)}`;
}

/** The query for one this deployment refused. */
export function mcpOAuthRefused(failure: McpOAuthFailure): string {
  return `mcp_oauth=error&reason=${failure}`;
}

/**
 * The query for one the provider or the backend refused, in their own words.
 *
 * Passed through rather than mapped to a code: what they wrote is the only
 * account of the refusal there is, and this side cannot translate a sentence it
 * did not write.
 */
export function mcpOAuthUpstreamRefusal(reason: string): string {
  return `mcp_oauth=error&reason=${encodeURIComponent(reason)}`;
}

/** The outcome a URL carries, or `null` when it carries none. */
export function readMcpOAuthOutcome(search: string): McpOAuthOutcome | null {
  const params = new URLSearchParams(search);
  const status = params.get("mcp_oauth");
  if (status === null) return null;
  if (status === "success") return { status: "success", name: params.get("name") ?? "" };
  return { status: "error", reason: params.get("reason") || "AUTHORIZATION_FAILED" };
}

/** What to tell the person about it. */
export function mcpOAuthMessage(outcome: McpOAuthOutcome, t: Translate): string {
  if (outcome.status === "success") {
    return outcome.name === ""
      ? t("oauthConnectedUnnamed")
      : t("oauthConnected", { name: outcome.name });
  }
  const key = FAILURE_KEYS[outcome.reason as McpOAuthFailure];
  return key === undefined ? outcome.reason : t(key);
}
