/**
 * The baked-in brand logos for MCP servers.
 *
 * This module used to hold a curated catalog of its own - fourteen servers with their
 * own descriptions, examples and category headings. Nothing rendered it: the catalog
 * the product shows is served by the backend from
 * `app/core/catalog/mcp_servers.json`, is fifty-nine entries deep, and has its own
 * categories, so the table here was a superseded copy that could only ever disagree
 * with it. Its copy was dead English, which is why it was deleted rather than
 * translated when the guard first read a `.ts` file (#446).
 */

import { MCP_LOGOS } from "./mcp-logos.generated";

/**
 * Last-resort logo source: Google's favicon service, tokenless and over HTTPS.
 * Only reached for a domain missing from {@link MCP_LOGOS} - every catalog
 * entry should be baked in, so hitting this means `bun run gen:mcp-logos`
 * needs a re-run. Not exported: nothing should request it on purpose.
 */
function faviconServiceUrl(domain: string): string {
  return `https://www.google.com/s2/favicons?sz=128&domain=${encodeURIComponent(domain)}`;
}

/**
 * Brand logo for a catalog domain, as a baked-in data URI ({@link MCP_LOGOS}).
 *
 * Used everywhere a catalog logo is shown - the Settings marketplace and the
 * demo-only MCP badge alike. Baked rather than fetched for two reasons: the
 * self-contained export has no network, and a live app shouldn't tell a third
 * party which plugins its users are looking at. Regenerate the map with
 * `bun run gen:mcp-logos` after adding a catalog entry.
 */
export function logoDataUri(domain: string): string {
  return MCP_LOGOS[domain] ?? faviconServiceUrl(domain);
}
