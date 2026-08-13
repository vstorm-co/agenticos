import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { logoDataUri } from "./mcp-catalog";
import { MCP_LOGOS } from "./mcp-logos.generated";

describe("logoDataUri", () => {
  it("answers with the baked-in logo, so no page tells a third party what it is showing", () => {
    expect(logoDataUri("mcp.linear.app")).toMatch(/^data:/);
  });

  it("falls back to the favicon service for a domain nobody generated", () => {
    // Reaching this in the app means `bun run gen:mcp-logos` needs a re-run; it
    // is a stale-build signal rather than a state to design for.
    expect(logoDataUri("not-in-the-map.example")).toBe(
      "https://www.google.com/s2/favicons?sz=128&domain=not-in-the-map.example",
    );
  });
});

describe("MCP_LOGOS", () => {
  it("holds a key for every catalog server's URL host, so the badge renders offline (#614)", () => {
    // The lookup asks with the connection URL's host (`mcp.linear.app`), never a
    // brand domain (`linear.app`); a map keyed on anything else is 29 KB nothing
    // reads. Scoped to entries with a URL: a self-hosted server's host is not
    // knowable at build time and the favicon fallback is right for it.
    const catalog = join(
      process.cwd(),
      "..",
      "backend",
      "app",
      "core",
      "catalog",
      "mcp_servers.json",
    );
    const entries = JSON.parse(readFileSync(catalog, "utf8")) as {
      key: string;
      url: string | null;
    }[];
    const hosted = entries.filter((entry) => entry.url);
    expect(hosted.length).toBeGreaterThan(0);
    for (const entry of hosted) {
      const host = new URL(entry.url as string).hostname;
      expect(
        MCP_LOGOS[host],
        `${entry.key}: no baked logo for ${host} — run bun run gen:mcp-logos`,
      ).toMatch(/^data:/);
    }
  });
});
