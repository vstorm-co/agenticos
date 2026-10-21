/**
 * Brand marks as base64 data URIs, shared by the logo generators: the catalog's
 * MCP servers and the knowledge-base connectors.
 */

/** Google's favicon service — follows redirects to the actual PNG. */
export function faviconUrl(domain: string): string {
  return `https://www.google.com/s2/favicons?sz=128&domain=${encodeURIComponent(domain)}`;
}

/** The image at `url`, inlined, or null when it could not be fetched. */
export async function fetchAsDataUri(url: string): Promise<string | null> {
  try {
    const res = await fetch(url, { redirect: "follow" });
    if (!res.ok) return null;
    const type = res.headers.get("content-type") ?? "image/png";
    const b64 = Buffer.from(await res.arrayBuffer()).toString("base64");
    return `data:${type};base64,${b64}`;
  } catch {
    return null;
  }
}

/** A domain's favicon, inlined. */
export function fetchDataUri(domain: string): Promise<string | null> {
  return fetchAsDataUri(faviconUrl(domain));
}
