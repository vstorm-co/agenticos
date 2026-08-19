/**
 * @vitest-environment node
 *
 * A server hop, forwarding bytes. jsdom would be the wrong global for it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxyBrandingImage } from "./branding-bytes";

function backendAnswers(
  body: BodyInit | null,
  { status = 200, headers = {} }: { status?: number; headers?: Record<string, string> } = {},
) {
  const mock = vi.fn().mockResolvedValue(new Response(body, { status, headers }));
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("serving a branding image through this app", () => {
  it("forwards the bytes unchanged", async () => {
    backendAnswers(new Uint8Array([0x89, 0x50, 0x4e, 0x47]), {
      headers: { "content-type": "image/png" },
    });

    const response = await proxyBrandingImage("logo", "?v=1");

    expect(response.status).toBe(200);
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(
      new Uint8Array([0x89, 0x50, 0x4e, 0x47]),
    );
  });

  it("forwards the type the backend decided rather than guessing one", async () => {
    // The backend read it from the stored file instead of letting anything infer it
    // from a suffix, which is the whole reason a non-image is refused there.
    backendAnswers("gif", { headers: { "content-type": "image/gif" } });

    const response = await proxyBrandingImage("favicon", "");

    expect(response.headers.get("content-type")).toBe("image/gif");
  });

  it("forwards the backend's cache policy, which the version token makes safe", async () => {
    backendAnswers("png", {
      headers: {
        "content-type": "image/png",
        "cache-control": "public, max-age=31536000, immutable",
      },
    });

    const response = await proxyBrandingImage("logo", "?v=9");

    expect(response.headers.get("cache-control")).toBe("public, max-age=31536000, immutable");
  });

  it("refuses content-type sniffing on the way out too", async () => {
    backendAnswers("png", { headers: { "content-type": "image/png" } });

    const response = await proxyBrandingImage("logo", "");

    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
  });

  it("passes the version through to the backend", async () => {
    const mock = backendAnswers("png", { headers: { "content-type": "image/png" } });

    await proxyBrandingImage("favicon", "?v=42");

    expect(mock.mock.calls[0]?.[0]).toContain("/branding/favicon?v=42");
  });

  it("forwards a 404 as itself", async () => {
    // Which is the ordinary answer for a deployment using the built-in mark, and
    // what the frontend reads as "draw your own".
    backendAnswers(null, { status: 404 });

    const response = await proxyBrandingImage("logo", "");

    expect(response.status).toBe(404);
  });

  it("forwards any other refusal as its own status", async () => {
    backendAnswers(null, { status: 503 });

    expect((await proxyBrandingImage("logo", "")).status).toBe(503);
  });

  it("answers a refusal when the backend cannot be reached at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("ECONNREFUSED")));

    const response = await proxyBrandingImage("logo", "");

    expect(response.status).toBe(500);
  });
});
