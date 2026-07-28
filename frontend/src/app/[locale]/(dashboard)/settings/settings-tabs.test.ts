import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { SETTINGS_TABS } from "./settings-tabs";

/**
 * The settings tab row is the section's index, and this suite is what keeps it
 * one.
 *
 * The row is a hand-written list next to a directory of routes, and the two had
 * silently drifted: `providers` and `mcp-servers` were pages under `/settings/`
 * that no tab led to, reachable only by knowing the URL. A list maintained by
 * hand drifts the moment someone adds a page, so the pairing is asserted rather
 * than remembered.
 *
 * Both halves matter. A page with no tab is unreachable from the row; a tab
 * with no page is a link in the product that 404s.
 */

// Spelled out from the vitest root rather than derived from `import.meta.url`,
// which under the jsdom environment is an http URL and not a path. Moving this
// suite away from the routes it guards makes `readdirSync` throw, which is the
// failure you want.
const SETTINGS_DIR = path.join(process.cwd(), "src/app/[locale]/(dashboard)/settings");

/** Every route segment under `/settings/` that actually renders a page. */
function settingsRouteSegments(): string[] {
  return readdirSync(SETTINGS_DIR, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .filter((entry) =>
      readdirSync(path.join(SETTINGS_DIR, entry.name)).some((file) => file === "page.tsx"),
    )
    .map((entry) => entry.name)
    .sort();
}

/** The segment a tab points at, or `null` if the tab leaves the section. */
function tabSegment(href: string): string | null {
  const match = /^\/settings\/([^/]+)$/.exec(href);
  return match?.[1] ?? null;
}

describe("the settings tab row", () => {
  it("leads to every page under /settings", () => {
    // The reported bug. `/settings/page.tsx` is not in this list: it is the
    // section index, and it redirects to the first tab rather than being one.
    const tabbed = SETTINGS_TABS.map((tab) => tabSegment(tab.href))
      .filter((segment): segment is string => segment !== null)
      .sort();

    expect(tabbed).toEqual(settingsRouteSegments());
  });

  it("leads only to pages that exist", () => {
    const routes = new Set(settingsRouteSegments());
    const broken = SETTINGS_TABS.filter((tab) => {
      const segment = tabSegment(tab.href);
      return segment === null || !routes.has(segment);
    });

    expect(broken).toEqual([]);
  });

  it("stays inside the section it indexes", () => {
    // A tab pointing outside `/settings/` would put that page in two
    // navigations at once - the tab row and the sidebar - with no rule about
    // which one is primary. That is why AI providers and MCP servers were moved
    // to the top level instead of being added here.
    const escaping = SETTINGS_TABS.filter((tab) => tabSegment(tab.href) === null);

    expect(escaping).toEqual([]);
  });

  it("names each destination once", () => {
    const hrefs = SETTINGS_TABS.map((tab) => tab.href);

    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
