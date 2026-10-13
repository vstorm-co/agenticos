/**
 * Types for MCP servers, mirroring the backend.
 *
 * Two different things live here and the difference is the whole design:
 *
 * - The **catalog** (`GET /agents/mcp-catalog`) is the organization-level list
 *   of servers the platform vouches for. It is curated and read-only - there is
 *   no endpoint that adds to it, so nothing in the UI may pretend there is.
 * - A **connection** (`/me/mcp-connections`) is a user's own credentialed link
 *   to one of those servers. It is the only writable half, and the only half
 *   that has an id.
 *
 * `McpConnectionRecord` deliberately is not redefined here - it already lives in
 * `@/lib/mcp-connections-api` next to the calls that return it.
 */

/** How a catalog server authenticates. The only thing that really varies. */
export type McpAuthKind = "none" | "token" | "oauth";

/** One connectable server in the organization catalog. */
export interface McpCatalogEntry {
  key: string;
  name: string;
  description: string;
  category: string;
  auth: McpAuthKind;
  /** Null when the organization self-hosts the server and supplies the URL. */
  url: string | null;
  docs_url: string | null;
  /** What to tell the person pasting a credential. */
  token_hint: string | null;
  /**
   * Whether somebody here checked this entry.
   *
   * True for the curated catalog: the auth flow works, the description is
   * honest, the token hint says what kind of credential to paste. False for a
   * server mirrored from the public registry, where the description is the
   * publisher's and there is no hint because the registry has no such field.
   *
   * Optional so a response from before this field renders as reviewed rather
   * than as suspect - the curated catalog is what those responses held.
   */
  reviewed?: boolean;
  /** Brand mark to draw, by name. Null falls back to a monogram. */
  icon: string | null;
}

export interface McpCatalog {
  items: McpCatalogEntry[];
  /** Matches across both sources, so a pager knows how many pages there are. */
  total: number;
  /**
   * How many servers the mirrored public registry holds.
   *
   * What the list *reaches*, as distinct from what this page matched. Zero until
   * `agenticos cmd mcp-registry-sync` has run, which is what a fresh install
   * shows a curated-only list for.
   */
  registry_total?: number;
}

/**
 * Where a catalog server stands for the current user.
 *
 * "connected" is the only state in which an agent can actually reach the
 * server, so every other state is named after what is blocking it rather than
 * collapsed into a single "not ready".
 */
export type McpConnectionState =
  "not-connected" | "needs-authorization" | "disabled" | "error" | "connected";
