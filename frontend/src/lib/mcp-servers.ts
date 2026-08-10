/**
 * Turning three lists into the one thing a person is actually looking at.
 *
 * There are three layers here and the UI used to show two of them as peer
 * pages, which is what made "what is the difference between MCP servers and
 * Integrations?" a fair question with no good answer:
 *
 * - a **catalog entry** is a server that *exists* - deployment-wide, read-only,
 *   nothing to manage;
 * - a **connection** is a credential to one server, owned by a person or by the
 *   organization;
 * - a **binding** is which connection an agent may use, and lives in the spec.
 *
 * A catalog entry is not a sibling of a connection, it is what a connection
 * points at. So the catalog is the list, and connection state is a property of
 * a row rather than a second screen. Connections to servers the catalog does
 * not carry become rows of their own, so nothing is only reachable from a
 * surface that no longer exists.
 *
 * The join is done here because the API offers none, on the two things both
 * sides carry: `catalog_key` where the backend recorded it, then the URL, then
 * the name. The URL is what makes the fallback trustworthy - the catalog bakes
 * it in and the backend stores exactly the URL it validated - and the name is
 * the last resort for entries with no URL because the server is self-hosted.
 */

import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpAuthKind, McpCatalogEntry, McpConnectionState } from "@/types/mcp";

/** What a server asks for, said the way the person connecting it would say it. */
export const MCP_AUTH_LABEL: Record<McpAuthKind, string> = {
  none: "No credentials",
  token: "API token",
  oauth: "OAuth",
};

/**
 * What state a connection is in, as a key in the `mcp` namespace.
 *
 * A module cannot call a translator, so it holds the key and the component
 * translates at the point of use. It held the English word instead, while
 * `mcp.connected` and `mcp.notConnected` sat in the catalog with nothing reading
 * them - the state on every row of the MCP list and of the builder's picker was
 * English under every locale (#425).
 *
 * `MCP_AUTH_LABEL` above is still a word rather than a key, as is `SCOPE_LABEL`
 * in `mcp-server-list.tsx`: no catalog message holds either, so they are part of
 * the copy the guard has never read at all rather than part of this defect.
 */
export const MCP_STATE_LABEL: Record<McpConnectionState, string> = {
  "not-connected": "notConnected",
  "needs-authorization": "needsAuthorization",
  disabled: "stateDisabled",
  error: "unreachable",
  connected: "connected",
};

/** Trailing slashes and case are not a difference between two server URLs. */
function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, "").toLowerCase();
}

/**
 * The connection to *entry* among *connections*, or null if there is none.
 *
 * Generic over the record so the caller gets back the type it passed in - the
 * organization's servers carry a `catalog_key` a personal one does not, and
 * widening them to the shared shape here would lose it at the one call site
 * that wants it.
 */
function connectionForEntry<T extends McpConnectionRecord>(
  entry: McpCatalogEntry,
  connections: T[],
): T | null {
  // Recorded provenance beats any guess: the backend stored which entry this
  // came from, and a URL that has since been edited must not un-match it.
  const byKey = connections.find(
    (connection) => "catalog_key" in connection && connection.catalog_key === entry.key,
  );
  if (byKey) return byKey;
  if (entry.url) {
    const target = normalizeUrl(entry.url);
    const byUrl = connections.find((connection) => normalizeUrl(connection.url) === target);
    if (byUrl) return byUrl;
  }
  return connections.find((connection) => connection.name === entry.key) ?? null;
}

/** The catalog entry *connection* points at, or null for a server we do not list. */
export function entryForConnection(
  connection: McpConnectionRecord,
  catalog: McpCatalogEntry[],
): McpCatalogEntry | null {
  const url = normalizeUrl(connection.url);
  const byUrl = catalog.find((entry) => entry.url !== null && normalizeUrl(entry.url) === url);
  if (byUrl) return byUrl;
  return catalog.find((entry) => entry.key === connection.name) ?? null;
}

/**
 * What is standing between this connection and a working server.
 *
 * The order is the order in which a person has to fix things. An OAuth
 * connection that was never authorized has no credentials at all, so reporting
 * it as "disabled" or as a stale error would send someone to the wrong control.
 */
export function connectionState(connection: McpConnectionRecord | null): McpConnectionState {
  if (!connection) return "not-connected";
  if (connection.auth_type === "oauth" && !connection.oauth_authorized)
    return "needs-authorization";
  if (!connection.is_enabled) return "disabled";
  if (connection.last_status === "error") return "error";
  return "connected";
}

/**
 * One row of the merged list: a server, and who has connected it.
 *
 * `entry` is null for a server nobody curated - somebody's own URL. Those are
 * rows too, because a connection that exists and is reachable from no screen is
 * a credential nobody can revoke.
 */
export interface McpServerRow {
  /** Stable across renders: the catalog key, or the connection this row is. */
  key: string;
  name: string;
  description: string;
  category: string;
  auth: McpAuthKind;
  url: string | null;
  docsUrl: string | null;
  tokenHint: string | null;
  /** The catalog entry this row is, or null for a custom server. */
  entry: McpCatalogEntry | null;
  /** The organization's connection - the only kind an agent can be bound to. */
  organization: OrgMcpConnectionRecord | null;
  /** The caller's own connection, used by their assistant and nothing else. */
  personal: McpConnectionRecord | null;
}

/** Where custom servers sort, and what the heading over them says. */
export const CUSTOM_CATEGORY = "custom";

/**
 * The catalog, with every connection folded onto the row it belongs to.
 *
 * Catalog order is preserved and custom servers follow, so the list reads as
 * "what you can connect" rather than "what happens to be in the database" -
 * which is the difference between a catalog and a dump.
 */
export function mergeServers(
  catalog: McpCatalogEntry[],
  organization: OrgMcpConnectionRecord[],
  personal: McpConnectionRecord[],
): McpServerRow[] {
  const claimed = new Set<string>();

  const rows: McpServerRow[] = catalog.map((entry) => {
    const org = connectionForEntry(entry, organization);
    const own = connectionForEntry(entry, personal);
    if (org) claimed.add(org.id);
    if (own) claimed.add(own.id);
    return {
      key: entry.key,
      name: entry.name,
      description: entry.description,
      category: entry.category,
      auth: entry.auth,
      url: entry.url,
      docsUrl: entry.docs_url,
      tokenHint: entry.token_hint,
      entry,
      organization: org,
      personal: own,
    };
  });

  const custom = (connection: McpConnectionRecord, isOrg: boolean): McpServerRow => ({
    key: connection.id,
    name: connection.name,
    description: isOrg
      ? "Added by this organization, not from the catalog."
      : "Added by you, not from the catalog.",
    category: CUSTOM_CATEGORY,
    auth: connection.auth_type === "oauth" ? "oauth" : connection.has_auth_token ? "token" : "none",
    url: connection.url,
    docsUrl: null,
    tokenHint: null,
    entry: null,
    organization: isOrg ? (connection as OrgMcpConnectionRecord) : null,
    personal: isOrg ? null : connection,
  });

  return [
    ...rows,
    ...organization.filter((c) => !claimed.has(c.id)).map((c) => custom(c, true)),
    ...personal.filter((c) => !claimed.has(c.id)).map((c) => custom(c, false)),
  ];
}
