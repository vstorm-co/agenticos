import { describe, expect, it } from "vitest";

import type { McpConnectionRecord } from "./mcp-connections-api";
import type { OrgMcpConnectionRecord } from "./org-mcp-connections-api";
import { CUSTOM_CATEGORY, connectionState, mergeServers } from "./mcp-servers";
import type { McpCatalogEntry } from "@/types/mcp";

const GITHUB: McpCatalogEntry = {
  key: "github",
  name: "GitHub",
  description: "Read issues and pull requests.",
  category: "development",
  auth: "token",
  url: "https://api.githubcopilot.com/mcp/",
  docs_url: null,
  token_hint: null,
  icon: null,
};

const POSTGRES: McpCatalogEntry = {
  key: "postgres",
  name: "PostgreSQL",
  description: "Query read-only views.",
  category: "data",
  auth: "token",
  // Self-hosted: nothing to match a URL against.
  url: null,
  docs_url: null,
  token_hint: null,
  icon: null,
};

function personal(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "p1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "bearer",
    oauth_authorized: false,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: null,
    is_default: false,
    label: null,
    last_tools: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function organization(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return { ...personal(), id: "o1", catalog_key: "github", granted_scopes: null, ...overrides };
}

describe("mergeServers", () => {
  it("folds both owners onto the row for the server they point at", () => {
    // The whole reason the two pages became one: "who has connected this" is a
    // property of a server, not a separate destination.
    const rows = mergeServers([GITHUB], [organization()], [personal()]);

    expect(rows).toHaveLength(1);
    expect(rows[0]?.organizations[0]?.id).toBe("o1");
    expect(rows[0]?.personals[0]?.id).toBe("p1");
  });

  it("trusts the recorded catalog key over the URL", () => {
    // The URL is editable. A connection made from the catalog and then pointed
    // at a proxy is still that catalog server, and losing the match would show
    // it twice: once as unconnected GitHub, once as a stranger.
    const rows = mergeServers(
      [GITHUB],
      [organization({ url: "https://proxy.internal/github" })],
      [],
    );

    expect(rows).toHaveLength(1);
    expect(rows[0]?.organizations[0]?.id).toBe("o1");
  });

  it("falls back to the name for a server the organization hosts itself", () => {
    // A self-hosted entry has no URL to compare, so the name is all there is.
    const rows = mergeServers(
      [POSTGRES],
      [],
      [personal({ name: "postgres", url: "https://pg/mcp" })],
    );

    expect(rows[0]?.personals[0]?.id).toBe("p1");
  });

  it("gives a connection the catalog does not carry a row of its own", () => {
    // Otherwise it is reachable from nowhere - a live credential nobody can
    // find to revoke, which is exactly what a merged page must not create.
    const rows = mergeServers(
      [GITHUB],
      [],
      [personal({ id: "p9", name: "crm", url: "https://crm/mcp" })],
    );

    expect(rows.map((row) => row.key)).toEqual(["github", "p9"]);
    expect(rows[1]?.category).toBe(CUSTOM_CATEGORY);
    expect(rows[1]?.entry).toBeNull();
    expect(rows[1]?.personals[0]?.id).toBe("p9");
  });

  it("never lists a connection twice", () => {
    const rows = mergeServers([GITHUB], [organization()], [personal()]);

    expect(rows.filter((row) => row.category === CUSTOM_CATEGORY)).toEqual([]);
  });

  it("keeps catalog order and puts custom servers last", () => {
    // The list is a catalog, and a catalog that reorders itself as people
    // connect things is a list of what is in the database instead.
    const rows = mergeServers(
      [GITHUB, POSTGRES],
      [],
      [personal({ id: "p9", name: "crm", url: "https://crm/mcp" })],
    );

    expect(rows.map((row) => row.key)).toEqual(["github", "postgres", "p9"]);
  });

  it("says who added a custom server, because that decides who can bind it", () => {
    // An organization's own server is agent-bindable; somebody's personal one is
    // not, and the row is the only place that distinction is written.
    const rows = mergeServers(
      [],
      [organization({ id: "o9", name: "internal", url: "https://internal/mcp" })],
      [personal({ id: "p9", name: "crm", url: "https://crm/mcp" })],
    );

    // The key, not the sentence: a custom row's description is this app's own copy and
    // the component translates it, where a catalog row carries the backend's text.
    expect(rows.map((row) => row.descriptionKey)).toEqual(["customAddedByOrg", "customAddedByYou"]);
    expect(rows[0]?.organizations[0]?.id).toBe("o9");
    expect(rows[0]?.personals).toEqual([]);
  });

  it("reads a custom server's auth kind off the connection, since no entry declares one", () => {
    const rows = mergeServers(
      [],
      [],
      [
        personal({ id: "a", name: "open", url: "https://a/mcp", has_auth_token: false }),
        personal({ id: "b", name: "tokened", url: "https://b/mcp", has_auth_token: true }),
        personal({ id: "c", name: "consented", url: "https://c/mcp", auth_type: "oauth" }),
      ],
    );

    expect(rows.map((row) => row.auth)).toEqual(["none", "token", "oauth"]);
  });
});

/**
 * What a connection's state is, in one word.
 *
 * The order of the checks is the whole function: an OAuth server nobody
 * authorized answers nothing however enabled it is, and a disabled one answers
 * nothing however healthy its last check was. Reporting the wrong one sends
 * somebody to fix a credential that is fine.
 */
describe("connectionState", () => {
  it("says a server nobody connected is not connected", () => {
    expect(connectionState(null)).toBe("not-connected");
  });

  it("says an unauthorized OAuth server needs authorization, before anything else", () => {
    expect(
      connectionState(personal({ auth_type: "oauth", oauth_authorized: false, is_enabled: false })),
    ).toBe("needs-authorization");
  });

  it("says a switched-off server is disabled, whatever its last check said", () => {
    expect(connectionState(personal({ is_enabled: false, last_status: "error" }))).toBe("disabled");
  });

  it("says a server whose last check failed is unreachable", () => {
    expect(connectionState(personal({ last_status: "error" }))).toBe("error");
  });

  it("says an authorized, enabled, healthy server is connected", () => {
    expect(connectionState(personal({ auth_type: "oauth", oauth_authorized: true }))).toBe(
      "connected",
    );
  });
});

describe("several accounts on one server", () => {
  /**
   * An organization may hold a read-only Notion and an admin one. Uniqueness is
   * `(organization_id, name)` rather than per catalog entry, so this is a
   * supported shape - and the extras used to fall through as "custom" rows,
   * which is where a second account went to be mislabelled.
   */
  function orgFor(id: string, name: string): OrgMcpConnectionRecord {
    return { ...personal({ id, name }), catalog_key: "github" } as OrgMcpConnectionRecord;
  }

  it("keeps one row for the server and lists every connection on it", () => {
    const rows = mergeServers([GITHUB], [orgFor("o1", "gh"), orgFor("o2", "gh-admin")], []);

    // One card, not two that differ in nothing a reader can see.
    expect(rows).toHaveLength(1);
    expect(rows[0]?.organizations.map((c) => c.name)).toEqual(["gh", "gh-admin"]);
  });

  it("does not label an extra account a custom server", () => {
    const rows = mergeServers([GITHUB], [orgFor("o1", "gh"), orgFor("o2", "gh-admin")], []);

    expect(rows.some((row) => row.category === CUSTOM_CATEGORY)).toBe(false);
    expect(rows[0]?.entry).not.toBeNull();
  });

  it("keeps the two owners apart on one row", () => {
    const rows = mergeServers(
      [GITHUB],
      [orgFor("o1", "gh"), orgFor("o2", "gh-admin")],
      [personal({ id: "p1", name: "gh-mine" })],
    );

    expect(rows[0]?.organizations).toHaveLength(2);
    expect(rows[0]?.personals.map((c) => c.id)).toEqual(["p1"]);
  });

  it("still sends a server the catalog does not describe to the custom rows", () => {
    // Neither its URL nor its name points at an entry - the three ways a
    // connection is matched, all missed.
    const rows = mergeServers(
      [GITHUB],
      [],
      [personal({ id: "x", name: "ours", url: "https://elsewhere/mcp" })],
    );

    expect(rows.at(-1)?.category).toBe(CUSTOM_CATEGORY);
  });
});
