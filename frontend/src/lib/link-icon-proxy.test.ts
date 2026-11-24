import { afterEach, describe, expect, it, vi } from "vitest";

import { proxyLinkIcon } from "./link-icon-proxy";

afterEach(() => vi.unstubAllGlobals());

describe("link icon proxy", () => {
  it.each([
    null,
    "localhost",
    "127.0.0.1",
    "[::1]",
    "a.internal",
    "a.local",
    "https://site.com/",
    "a.com/path",
    "a.com?x=1",
    "a.com@other.com",
    "x".repeat(254),
  ])("refuses a non-public DNS name %s before making a request", async (host) => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect((await proxyLinkIcon(host)).status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("fetches only the fixed service without forwarding viewer credentials", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([1, 2, 3]), {
        headers: { "content-type": "image/png; charset=binary" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyLinkIcon("Example.COM");
    expect(fetcher).toHaveBeenCalledWith("https://icons.duckduckgo.com/ip3/example.com.ico", {
      credentials: "omit",
      redirect: "error",
      signal: expect.any(AbortSignal),
      next: { revalidate: 86400 },
    });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-security-policy")).toContain("sandbox");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
  });

  it.each([
    new Response("not found", { status: 404 }),
    new Response("<svg/>", { headers: { "content-type": "image/svg+xml" } }),
    new Response("html", { headers: { "content-type": "text/html" } }),
    new Response("unknown"),
    new Response(null, { headers: { "content-type": "image/png" } }),
    new Response(new Uint8Array(65537), { headers: { "content-type": "image/png" } }),
  ])("refuses unavailable, active or oversized content", async (upstream) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(upstream));
    expect((await proxyLinkIcon("example.com")).status).toBe(404);
  });

  it("contains network failures and redirect refusal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("redirect refused")));
    expect((await proxyLinkIcon("example.com")).status).toBe(404);
  });
});
