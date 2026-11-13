/** @vitest-environment node */
import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

import { ACCESS_TOKEN_COOKIE } from "@/lib/session-cookie";
import { GET } from "./route";

afterEach(() => vi.unstubAllGlobals());

it("refuses an unauthenticated icon request without outbound traffic", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  expect(
    (await GET(new NextRequest("http://localhost/api/link-icon?host=example.com"))).status,
  ).toBe(401);
  expect(fetcher).not.toHaveBeenCalled();
});

it("forwards only the hostname to the icon service", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response("icon", { headers: { "content-type": "image/png" } }));
  vi.stubGlobal("fetch", fetcher);
  const request = new NextRequest("http://localhost/api/link-icon?host=example.com");
  request.cookies.set(ACCESS_TOKEN_COOKIE, "private-session");
  expect((await GET(request)).status).toBe(200);
  const [url, options] = fetcher.mock.calls[0] ?? [];
  expect(url).toBe("https://icons.duckduckgo.com/ip3/example.com.ico");
  expect(JSON.stringify(options)).not.toContain("private-session");
});
