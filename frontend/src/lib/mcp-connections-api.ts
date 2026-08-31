/**
 * API client for user-scoped MCP server connections (Settings → Integrations).
 *
 * Each record points at a remote MCP server the assistant can pull tools
 * from. The bearer token is write-only: the backend stores it encrypted and
 * responses only carry `has_auth_token`.
 */

import { apiClient } from "./api-client";

export interface McpConnectionRecord {
  id: string;
  name: string;
  url: string;
  has_auth_token: boolean;
  /** null = every tool the server offers is exposed to the agent. */
  allowed_tools: string[] | null;
  is_enabled: boolean;
  /** "bearer" (static token) or "oauth" (authorization-code flow). */
  auth_type: "bearer" | "oauth";
  /** OAuth connection that finished consent and has usable tokens. */
  oauth_authorized: boolean;
  /** Result of the most recent connectivity check ("ok" / "error"), if any. */
  last_status: string | null;
  last_error: string | null;
  last_checked_at: string | null;
  /** Which catalog entry it points at, where it was connected from one. */
  catalog_key: string | null;
  /**
   * What a person reads. `name` is the tool prefix and is constrained to what a
   * tool name can carry, which makes it a poor label for two accounts on one
   * service. Null is not a gap: the slug is what the connection always showed.
   */
  label: string | null;
  /**
   * Speak as this account where an agent binding asked for the member's own and
   * they hold several on this service. At most one of theirs per service, kept
   * so by a partial unique index (#1342).
   */
  is_default: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface McpToolInfo {
  name: string;
  description: string;
}

export interface McpConnectionTestResult {
  ok: boolean;
  error: string | null;
  tools: McpToolInfo[];
}

interface McpConnectionList {
  items: McpConnectionRecord[];
  total: number;
}

const ROOT = "/me/mcp-connections";
/** The organization's own router, mounted beside `/me/...` rather than under `/orgs`. */
const ORG_ROOT = "/mcp-connections";

export async function listMcpConnections(): Promise<McpConnectionRecord[]> {
  const data = await apiClient.get<McpConnectionList>(ROOT);
  return data.items;
}

export async function createMcpConnection(input: {
  name: string;
  url: string;
  auth_token?: string;
  allowed_tools?: string[] | null;
  is_enabled?: boolean;
  label?: string;
}): Promise<McpConnectionRecord> {
  return apiClient.post<McpConnectionRecord>(ROOT, input);
}

export async function updateMcpConnection(
  id: string,
  patch: {
    name?: string;
    url?: string;
    /** "" clears the stored token. */
    auth_token?: string;
    allowed_tools?: string[];
    clear_allowed_tools?: boolean;
    is_enabled?: boolean;
    /** Speak as this one where an agent asked for the member's own account. */
    is_default?: boolean;
    /** `""` clears it, back to showing the slug. */
    label?: string;
  },
): Promise<McpConnectionRecord> {
  return apiClient.patch<McpConnectionRecord>(`${ROOT}/${id}`, patch);
}

export async function deleteMcpConnection(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${id}`);
}

export async function testMcpConnection(id: string): Promise<McpConnectionTestResult> {
  return apiClient.post<McpConnectionTestResult>(`${ROOT}/${id}/test`);
}

/**
 * Begin the OAuth flow for a server. Returns the provider consent URL - the
 * caller redirects the browser there; the provider sends the user back to the
 * `/oauth/callback` route, which finishes the exchange.
 */
export async function startMcpOAuth(
  input: { name: string; url: string },
  scope: "personal" | "organization" = "personal",
): Promise<{ authorization_url: string }> {
  // Two endpoints, one flow. Which one decides who *holds* the connection when
  // the provider sends the browser back - the person who consented, or the
  // organization they consented on behalf of.
  //
  // The organization's router is mounted at `/mcp-connections`, not under
  // `/orgs` - that prefix belongs to organizations, members and invitations.
  // It read `/orgs/mcp-connections` until #1340, so every organization-scoped
  // consent 404ed before it left the browser.
  const root = scope === "organization" ? ORG_ROOT : ROOT;
  return apiClient.post<{ authorization_url: string }>(`${root}/oauth/start`, input);
}

/**
 * Begin the GitHub OAuth App flow for a trigger portal, on the organization.
 *
 * GitHub does not support the discovery-and-registration flow `startMcpOAuth`
 * runs, so it has its own endpoint: the backend reads the organization's stored
 * `github_oauth_app` secret and builds GitHub's consent URL for the portal's
 * scopes. A 404 ("add a GitHub OAuth App secret first") or a 400 (the portal
 * does not connect through GitHub) arrives as the backend's own message, which
 * the caller shows rather than a generic failure.
 */
export async function startGithubOrgOAuth(
  portalKey: string,
): Promise<{ authorization_url: string }> {
  return apiClient.post<{ authorization_url: string }>("/mcp-connections/oauth/start/github", {
    portal_key: portalKey,
  });
}

/**
 * Begin consent for a portal the platform *polls* rather than is posted to.
 *
 * Gmail's case: nothing registers a webhook, so the flow's only job is a
 * refreshable token carrying the portal's read scopes. It uses the deployment's
 * own Google client rather than a per-organization OAuth App, so a deployment with
 * none configured answers 404 and the card shows it as a prerequisite.
 */
export async function startPolledPortalOAuth(
  portalKey: string,
): Promise<{ authorization_url: string }> {
  return apiClient.post<{ authorization_url: string }>("/mcp-connections/oauth/start/portal", {
    portal_key: portalKey,
  });
}
