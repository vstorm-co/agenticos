import type { Translate } from "@/lib/agent-step-captions";
import { isSafeReturnPath } from "@/lib/safe-return-path";

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
 *
 * The callback takes no session by design - the `state` token is what
 * authenticates the exchange - so **anyone can put a browser on this URL with a
 * refusal of their choosing**. Two things follow, and both are load-bearing now
 * that the outcome is rendered rather than ignored. A refusal of ours travels
 * under its own parameter and is looked up in `FAILURE_KEYS`, so a stranger
 * cannot spell one and have the product say it in its own voice. And text from
 * anywhere else is stripped of control characters, capped, and shown quoted
 * after a refusal this repository wrote, so a toast never reads as an
 * instruction from us.
 */

/** A refusal written in this repository, and therefore translatable. */
export type McpOAuthFailure = "AUTHORIZATION_FAILED" | "MISSING_AUTHORIZATION_CODE";

/** Copy for each, under the `mcp` namespace. */
const FAILURE_KEYS: Record<McpOAuthFailure, string> = {
  AUTHORIZATION_FAILED: "oauthFailed",
  MISSING_AUTHORIZATION_CODE: "oauthMissingCode",
};

/** Long enough for a provider's sentence, short enough not to be a paragraph. */
const DETAIL_LIMIT = 200;

/** Everything the redirect adds, so the reader can take it all back off again. */
export const MCP_OAUTH_PARAMS = [
  "mcp_oauth",
  "mcp_oauth_name",
  "mcp_oauth_failure",
  "mcp_oauth_detail",
] as const;

export type McpOAuthOutcome =
  | { status: "success"; name: string }
  | { status: "error"; failure: McpOAuthFailure }
  | { status: "upstream-error"; detail: string };

/** The query for a consent that finished, naming the connection it created. */
export function mcpOAuthConnected(name: string): string {
  return `mcp_oauth=success&mcp_oauth_name=${encodeURIComponent(name)}`;
}

/** The query for one this deployment refused. */
export function mcpOAuthRefused(failure: McpOAuthFailure): string {
  return `mcp_oauth=error&mcp_oauth_failure=${failure}`;
}

/** The query for one the provider or the backend refused, in their own words. */
export function mcpOAuthUpstreamRefusal(detail: string): string {
  return `mcp_oauth=error&mcp_oauth_detail=${encodeURIComponent(detail)}`;
}

/** What survives of a sentence written outside this repository. */
function readable(detail: string): string {
  return detail.replace(/\p{C}/gu, " ").trim().slice(0, DETAIL_LIMIT).trim();
}

export function readMcpOAuthOutcome(search: string): McpOAuthOutcome | null {
  const params = new URLSearchParams(search);
  const status = params.get("mcp_oauth");
  if (!status) return null;
  if (status === "success") return { status: "success", name: params.get("mcp_oauth_name") ?? "" };
  const failure = params.get("mcp_oauth_failure");
  if (failure !== null && failure in FAILURE_KEYS) {
    return { status: "error", failure: failure as McpOAuthFailure };
  }
  const detail = readable(params.get("mcp_oauth_detail") ?? "");
  return detail === ""
    ? { status: "error", failure: "AUTHORIZATION_FAILED" }
    : { status: "upstream-error", detail };
}

export function mcpOAuthMessage(outcome: McpOAuthOutcome, t: Translate): string {
  switch (outcome.status) {
    case "success":
      return outcome.name === ""
        ? t("oauthConnectedUnnamed")
        : t("oauthConnected", { name: outcome.name });
    case "error":
      return t(FAILURE_KEYS[outcome.failure]);
    case "upstream-error":
      return t("oauthRefusedWithReason", { reason: outcome.detail });
  }
}

/**
 * Where the browser should land after the provider's consent, when not the
 * servers page.
 *
 * A cookie rather than a query parameter through the provider: the OAuth `state`
 * is the backend's and carries nothing of ours, and the redirect URI is fixed at
 * the provider, so the only channel from "start" to "callback" that stays on this
 * origin is the browser itself. Ten minutes is longer than any consent screen
 * and shorter than a forgotten tab.
 */
export const MCP_OAUTH_RETURN_COOKIE = "mcp_oauth_return";

/** Remember to come back to `path` once the consent lands. */
export function rememberMcpOAuthReturn(path: string): void {
  document.cookie = `${MCP_OAUTH_RETURN_COOKIE}=${encodeURIComponent(path)}; path=/; max-age=600; SameSite=Lax`;
}

/**
 * The remembered return path, if it is one of this app's own.
 *
 * Through `isSafeReturnPath`, the same guard the sign-in landing uses: the
 * cookie is the browser's to set, and a redirect target is exactly what an
 * open-redirect check exists for. Null means the servers page.
 *
 * A cookie that is not valid percent-encoding is a refusal too, not a crash:
 * `decodeURIComponent("%E0")` throws, and this runs inside the route the
 * provider redirects to - so an unthrown `URIError` would answer somebody
 * returning from a consent screen with a 500.
 */
export function safeMcpOAuthReturn(raw: string | undefined, origin: string): string | null {
  if (raw === undefined) return null;
  let path: string;
  try {
    path = decodeURIComponent(raw);
  } catch {
    return null;
  }
  return isSafeReturnPath(path, origin) ? path : null;
}

/**
 * This page's own path and query, for `returnTo` - or nothing on the server,
 * where there is no page yet. A client component still renders once there, and
 * the value is read on a click, never in the markup, so the two renders agreeing
 * is not required.
 */
export function hereForMcpOAuthReturn(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return `${window.location.pathname}${window.location.search}`;
}
