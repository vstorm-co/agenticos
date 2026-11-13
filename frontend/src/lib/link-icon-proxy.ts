const MAX_ICON_BYTES = 64 * 1024;
const RASTER_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "image/x-icon",
  "image/vnd.microsoft.icon",
]);

/**
 * Resolve icons through one fixed public service, never a model-supplied origin.
 * Only the DNS name leaves this server: no URL path, cookies or viewer address.
 * Redirects are refused so the service cannot turn this into an arbitrary proxy.
 */
export async function proxyLinkIcon(host: string | null): Promise<Response> {
  if (
    !host ||
    host.length > 253 ||
    !/^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(host) ||
    /\.(?:localhost|local|internal|invalid|test)$/i.test(host)
  )
    return new Response(null, { status: 400 });

  try {
    const response = await fetch(`https://icons.duckduckgo.com/ip3/${host.toLowerCase()}.ico`, {
      credentials: "omit",
      redirect: "error",
      signal: AbortSignal.timeout(3000),
      next: { revalidate: 86400 },
    });
    const type = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
    if (!response.ok || !type || !RASTER_TYPES.has(type) || !response.body) {
      await response.body?.cancel();
      return new Response(null, { status: 404 });
    }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_ICON_BYTES) return new Response(null, { status: 404 });
        chunks.push(value);
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return new Response(bytes, {
      headers: {
        "Content-Type": type,
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
      },
    });
  } catch {
    // Icons are optional decoration: refusal, timeout or upstream failure uses the globe.
    return new Response(null, { status: 404 });
  }
}
