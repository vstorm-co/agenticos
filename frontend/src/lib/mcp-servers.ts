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

/**
 * What a server asks for, as a key in the `mcp` namespace.
 *
 * Keys rather than words, for the reason `MCP_STATE_LABEL` gives below: a module
 * cannot call a translator, so the component translates at the point of use. It held
 * the English until the offence sweep learned to read a `.ts` file (#446).
 */
export const MCP_AUTH_LABEL: Record<McpAuthKind, string> = {
  none: "authNoCredentials",
  token: "authApiToken",
  oauth: "authOauth",
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
 * Every connection that points at one catalog entry, in order.
 *
 * An organization may hold several - a Notion read-only, a Notion admin - and
 * uniqueness is on the name rather than on the entry, so this is a supported
 * shape rather than a mistake. Matching runs the same three ways as the
 * singular version, and a connection matched by one is not matched again by the
 * next.
 */
function connectionsForEntry<T extends McpConnectionRecord>(
  entry: McpCatalogEntry,
  connections: T[],
): T[] {
  const target = entry.url === null ? null : normalizeUrl(entry.url);
  return connections.filter(
    (connection) =>
      ("catalog_key" in connection && connection.catalog_key === entry.key) ||
      (target !== null && normalizeUrl(connection.url) === target) ||
      connection.name === entry.key,
  );
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
  /**
   * The row's sentence, and where it came from decides which field holds it.
   *
   * A catalog row's is the backend's own - `app/core/catalog/mcp_servers.json` writes
   * it, so it is API data rather than this app's copy and there is no key for it. A
   * custom row's is one of two of ours, which is a key under `mcp` (#446).
   */
  description: string | null;
  descriptionKey: string | null;
  category: string;
  auth: McpAuthKind;
  url: string | null;
  docsUrl: string | null;
  tokenHint: string | null;
  /** The catalog entry this row is, or null for a custom server. */
  entry: McpCatalogEntry | null;
  /**
   * The organization's connections - the only kind an agent can be bound to.
   *
   * A list, because an organization may hold several accounts on one server: a
   * read-only Notion and an admin one are two connections with two names, and
   * the name is the tool prefix that tells them apart. One row per *server*
   * with a list inside it, rather than a card per connection - two identical
   * cards side by side read as a bug rather than as two accounts.
   */
  organizations: OrgMcpConnectionRecord[];
  /** The caller's own, used by their assistant and nothing else. */
  personals: McpConnectionRecord[];
}

/** Where custom servers sort, and what the heading over them says. */
export const CUSTOM_CATEGORY = "custom";

/** Whether this row is one somebody here vouched for. */
export function isReviewed(row: McpServerRow): boolean {
  return row.entry?.reviewed !== false;
}

/**
 * The catalog, with every connection folded onto the row it belongs to.
 *
 * Catalog order is preserved and custom servers follow, so the list reads as
 * "what you can connect" rather than "what happens to be in the database" -
 * which is the difference between a catalog and a dump.
 */
/**
 * The row one catalog entry makes, with nothing connected to it.
 *
 * Its own function because two callers need it and only one of them is
 * merging: the Builder's connect dialog wants the row for a single entry, and
 * taking `mergeServers(...)[0]` gave it a `McpServerRow | undefined` for a
 * case that cannot happen.
 */
export function rowForEntry(entry: McpCatalogEntry): McpServerRow {
  return {
    key: entry.key,
    name: entry.name,
    description: entry.description,
    descriptionKey: null,
    category: entry.category,
    auth: entry.auth,
    url: entry.url,
    docsUrl: entry.docs_url,
    tokenHint: entry.token_hint,
    entry,
    organizations: [],
    personals: [],
  };
}

export function rowsForEntries(
  entries: McpCatalogEntry[],
  organization: OrgMcpConnectionRecord[],
  personal: McpConnectionRecord[],
): McpServerRow[] {
  // One row per server, holding every connection to it. An entry with three
  // organization accounts is one card listing three, not three cards that
  // differ in nothing a reader can see - the extras used to fall through as
  // "custom" servers, which is where a second account went to be mislabelled.
  return entries.map((entry) => ({
    ...rowForEntry(entry),
    organizations: connectionsForEntry(entry, organization),
    personals: connectionsForEntry(entry, personal),
  }));
}

/**
 * Connections that match no catalog entry, as their own rows.
 *
 * **`catalog` has to be the whole catalog, not a page of it.** Whether a
 * connection is "not in the catalog" is a question about every entry, so asking
 * it of a page answers "yes" for a connection whose entry is on a different
 * page - and the Notion connection then appeared as an uncatalogued server at the
 * foot of every page, five times over, until a search for "notion" brought the
 * entry onto the page and it merged again.
 */
/**
 * The custom rows a search and a category filter leave standing.
 *
 * They are appended to the last page rather than fetched with it, so the
 * server's `query` and `category` never reached them: searching for an
 * unrelated server still listed every custom connection, and picking a curated
 * category listed rows whose category is `custom`. Applied here, before the row
 * count the page control divides by, so the count and the page agree.
 *
 * A custom row has a name and a URL and no description, so those two are what a
 * query can match - the same fields somebody typing a search would expect.
 */
/**
 * What a tool picker's state means as an allowlist: a list, or unrestricted.
 *
 * Null means "no narrowing from here", so tools the server adds later flow
 * through instead of silently staying off. It is only honest to write when the
 * catalogue on screen was a real probe.
 *
 * `probed` is the whole reason this is a function. A connection nothing has
 * probed has no catalogue, so the picker falls back to displaying the names the
 * binding already holds - and then "everything is checked" is true by
 * construction. Saving without touching anything rewrote a reviewed subset to
 * unrestricted, quietly handing the agent every tool the connection permits,
 * including write and destructive ones added since.
 */
export function narrowedSelection(
  checked: Set<string>,
  tools: readonly { name: string }[],
  probed: boolean,
): string[] | null {
  if (probed && checked.size === tools.length) return null;
  return [...checked];
}

export function matchingCustomRows(
  rows: McpServerRow[],
  query: string,
  category: string,
): McpServerRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (category && category !== CUSTOM_CATEGORY) return false;
    if (!needle) return true;
    return (
      row.name.toLowerCase().includes(needle) || (row.url ?? "").toLowerCase().includes(needle)
    );
  });
}

export function customRows(
  catalog: McpCatalogEntry[],
  organization: OrgMcpConnectionRecord[],
  personal: McpConnectionRecord[],
): McpServerRow[] {
  const claimed = new Set<string>();
  for (const entry of catalog) {
    for (const connection of [
      ...connectionsForEntry(entry, organization),
      ...connectionsForEntry(entry, personal),
    ]) {
      claimed.add(connection.id);
    }
  }

  const custom = (connection: McpConnectionRecord, isOrg: boolean): McpServerRow => ({
    key: connection.id,
    name: connection.name,
    description: null,
    descriptionKey: isOrg ? "customAddedByOrg" : "customAddedByYou",
    category: CUSTOM_CATEGORY,
    auth: connection.auth_type === "oauth" ? "oauth" : connection.has_auth_token ? "token" : "none",
    url: connection.url,
    docsUrl: null,
    tokenHint: null,
    entry: null,
    organizations: isOrg ? [connection as OrgMcpConnectionRecord] : [],
    personals: isOrg ? [] : [connection],
  });

  return [
    ...organization.filter((c) => !claimed.has(c.id)).map((c) => custom(c, true)),
    ...personal.filter((c) => !claimed.has(c.id)).map((c) => custom(c, false)),
  ];
}

/**
 * The whole catalog with every connection folded onto the row it belongs to.
 *
 * For a caller holding the entire catalog. The paged list cannot use this: it
 * has one page of entries, and `customRows` needs all of them to decide what is
 * uncatalogued.
 */
export function mergeServers(
  catalog: McpCatalogEntry[],
  organization: OrgMcpConnectionRecord[],
  personal: McpConnectionRecord[],
): McpServerRow[] {
  return [
    ...rowsForEntries(catalog, organization, personal),
    ...customRows(catalog, organization, personal),
  ];
}
