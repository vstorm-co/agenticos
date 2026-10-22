/**
 * @vitest-environment node
 *
 * A server route, run where it executes rather than in a browser-shaped global.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

const KEY = "W-Buc9zD7bZOzro8FYEOmOpGrNxFGuN7";
const FILE = "6758caa8aaff_video.mp4";
const TOKEN = `1792689903.${"b".repeat(64)}`;

let fetchMock: ReturnType<typeof vi.fn>;

function serve(
  body: BodyInit | null,
  { status = 200, headers = {} }: { status?: number; headers?: Record<string, string> } = {},
) {
  fetchMock = vi.fn().mockResolvedValue(new Response(body, { status, headers }));
  vi.stubGlobal("fetch", fetchMock);
}

function media({
  key = KEY,
  file = FILE,
  token = TOKEN as string | null,
  range = null as string | null,
} = {}) {
  const query = token === null ? "" : `?token=${encodeURIComponent(token)}`;
  const request = new NextRequest(
    `http://localhost:3000/api/embed/${key}/generated/${file}${query}`,
    { headers: range ? { range } : {} },
  );
  return GET(request, { params: Promise.resolve({ publicKey: key, filename: file }) });
}

afterEach(() => vi.unstubAllGlobals());

/**
 * A visitor's generated file, through the hosted page's own origin (#2309).
 *
 * The page has no session to forward, so this route forwards the link the
 * visitor's socket minted instead - and moves the bytes as a stream, because a
 * clip is played from here in ranges.
 */
describe("a generated file on a hosted page", () => {
  it("forwards the link, and no session, to the embed's route", async () => {
    serve("VIDEO", { headers: { "content-type": "video/mp4" } });

    const response = await media();

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("VIDEO");
    const [url, init] = fetchMock.mock.calls[0]! as [string, RequestInit];
    expect(url).toBe(`http://localhost:8000/api/v1/embed/${KEY}/generated/${FILE}?token=${TOKEN}`);
    expect(init.headers).toEqual({});
  });

  it("streams the body rather than reading it whole first", async () => {
    // The same stream object the backend answered with, handed straight on.
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("chunk"));
        controller.close();
      },
    });
    serve(stream, { headers: { "content-type": "video/mp4" } });

    const response = await media();

    await expect(response.text()).resolves.toBe("chunk");
  });

  it("passes a range up and the partial answer back, for Safari", async () => {
    serve("2345", {
      status: 206,
      headers: {
        "content-type": "video/mp4",
        "content-range": "bytes 2-5/10",
        "content-length": "4",
        "content-disposition": 'inline; filename="video.mp4"',
      },
    });

    const response = await media({ range: "bytes=2-5" });

    expect((fetchMock.mock.calls[0]![1] as RequestInit).headers).toEqual({ Range: "bytes=2-5" });
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 2-5/10");
    expect(response.headers.get("content-length")).toBe("4");
    expect(response.headers.get("accept-ranges")).toBe("bytes");
    expect(response.headers.get("content-disposition")).toBe('inline; filename="video.mp4"');
    await expect(response.text()).resolves.toBe("2345");
  });

  it("answers a range past the end with the length it was refused against", async () => {
    serve(null, { status: 416, headers: { "content-range": "bytes */10" } });

    const response = await media({ range: "bytes=99-" });

    expect(response.status).toBe(416);
    expect(response.headers.get("content-range")).toBe("bytes */10");
  });

  it("keeps a 416 well formed when the backend named no length", async () => {
    serve(null, { status: 416 });

    expect((await media({ range: "bytes=99-" })).headers.get("content-range")).toBe("");
  });

  it("pins the type, turns sniffing off and keeps it out of shared caches", async () => {
    serve("PNG", { headers: { "content-type": "image/png; charset=binary" } });

    const response = await media({ file: "abc_image.png" });

    expect(response.headers.get("content-type")).toBe("image/png");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-security-policy")).toBe("sandbox");
    expect(response.headers.get("cache-control")).toBe("private, max-age=3600");
  });

  it.each(["text/html", "image/svg+xml", "application/pdf", ""])(
    "refuses to pass on %s, because this origin is the one the page runs on",
    async (type) => {
      serve("<script>fetch('/api/v1/users/me')</script>", { headers: { "content-type": type } });

      expect((await media()).status).toBe(502);
    },
  );

  it("refuses an answer that names no type at all", async () => {
    serve(null);

    expect((await media()).status).toBe(502);
  });

  it("passes on the backend's refusal as a not-found", async () => {
    serve(JSON.stringify({ error: { code: "NOT_FOUND" } }), { status: 404 });

    const response = await media();

    expect(response.status).toBe(404);
    await expect(response.text()).resolves.toBe("");
  });

  it("passes on the link's spent allowance as a 429 with its interval", async () => {
    serve("{}", { status: 429, headers: { "retry-after": "60" } });

    const response = await media();

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("60");
    await expect(response.text()).resolves.toBe("");
  });

  it("keeps a 429 well formed when the backend named no interval", async () => {
    serve(null, { status: 429 });

    const response = await media();

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBeNull();
  });

  it("calls any other failure a bad gateway", async () => {
    serve("boom", { status: 500 });

    expect((await media()).status).toBe(502);
  });

  it("calls an unreachable backend a bad gateway", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    expect((await media()).status).toBe(502);
  });

  it.each([
    { key: "bad key!" },
    { file: "../secrets.png" },
    { file: ".hidden" },
    { token: null },
    { token: "forged" },
    { token: `0${TOKEN}` },
    { token: `${TOKEN}&download=true` },
  ])("refuses %o before reaching the network", async (given) => {
    serve("bytes", { headers: { "content-type": "image/png" } });

    const response = await media(given);

    expect(response.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
