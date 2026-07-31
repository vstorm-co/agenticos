import { describe, expect, it } from "vitest";

import { MCP_CATALOG, MCP_CATEGORIES, catalogBaseUrl, logoDataUri } from "./mcp-catalog";

/**
 * The curated plugin catalog.
 *
 * It is data, and the invariants are what stop a bad entry shipping: a card with
 * no category has no heading to appear under, an entry that says it takes a token
 * but says nothing about where to get one is a dead end, and a `{token}` URL that
 * is not marked `tokenPlacement: "url"` sends the placeholder to the provider
 * verbatim.
 */
describe("the MCP catalog", () => {
  it("puts every entry under a heading the marketplace renders", () => {
    const known = new Set(MCP_CATEGORIES.map((category) => category.id));

    for (const entry of MCP_CATALOG) {
      expect(known, entry.id).toContain(entry.category);
    }
  });

  it("gives every entry a stable id, used as the connection's name", () => {
    const ids = MCP_CATALOG.map((entry) => entry.id);

    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id, id).toMatch(/^[a-z0-9-]+$/);
  });

  it("says where to get the credential for every entry that needs one typed", () => {
    // Without it the card asks for a token and gives nobody a way to obtain one.
    for (const entry of MCP_CATALOG) {
      if (entry.auth === "token" || entry.auth === "personal-url") {
        expect(entry.tokenHelp, entry.id).toBeDefined();
        expect(entry.tokenHelp?.url, entry.id).toMatch(/^https:\/\//);
      }
    }
  });

  it("marks a URL carrying the token as one, and no other", () => {
    // A `{token}` left in a header-auth URL is sent to the provider literally.
    for (const entry of MCP_CATALOG) {
      const carriesToken = entry.url.includes("{token}");
      expect(carriesToken, entry.id).toBe(entry.tokenPlacement === "url");
    }
  });

  it("bakes in a URL for everything except the ones somebody pastes", () => {
    for (const entry of MCP_CATALOG) {
      if (entry.auth === "personal-url") expect(entry.url, entry.id).toBe("");
      else expect(entry.url, entry.id).toMatch(/^https:\/\//);
    }
  });
});

describe("catalogBaseUrl", () => {
  it("drops the query string, which is where a token lives", () => {
    // Matching a stored connection to its catalog entry cannot depend on the
    // credential embedded in the URL.
    expect(catalogBaseUrl("https://mcp.example/sse?apikey=secret")).toBe("https://mcp.example/sse");
  });

  it("leaves a URL that has no query string", () => {
    expect(catalogBaseUrl("https://mcp.example/sse")).toBe("https://mcp.example/sse");
  });
});

describe("logoDataUri", () => {
  it("answers with the baked-in logo, so no page tells a third party what it is showing", () => {
    const domain = MCP_CATALOG[0]!.domain;

    expect(logoDataUri(domain)).toMatch(/^data:/);
  });

  it("falls back to the favicon service for a domain nobody generated", () => {
    // Reaching this in the app means `bun run gen:mcp-logos` needs a re-run; it
    // is a stale-build signal rather than a state to design for.
    expect(logoDataUri("not-in-the-map.example")).toBe(
      "https://www.google.com/s2/favicons?sz=128&domain=not-in-the-map.example",
    );
  });
});
