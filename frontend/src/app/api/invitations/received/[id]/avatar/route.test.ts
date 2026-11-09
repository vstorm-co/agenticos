/** @vitest-environment node */
import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";
const params = { params: Promise.resolve({ id: "invite" }) };
function request(signedIn = true) {
  const req = new NextRequest("http://localhost:3000/api/invitations/received/invite/avatar");
  if (signedIn) req.cookies.set("agenticos_access_token", "session-token");
  return req;
}
afterEach(() => vi.unstubAllGlobals());
it("proxies the logo through the recipient's session without a tenant header", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(new Response("image", { headers: { "content-type": "image/png" } }));
  vi.stubGlobal("fetch", fetch);
  const result = await GET(request(), params);
  expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/v1/invitations/received/invite/avatar"),
    {
      headers: { Authorization: "Bearer session-token" },
      cache: "no-store",
    },
  );
  expect(result.status).toBe(200);
  expect(result.headers.get("cache-control")).toBe("private, no-store");
  expect(result.headers.get("x-content-type-options")).toBe("nosniff");
  expect(await result.text()).toBe("image");
});
it("does not fetch without authentication", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  expect((await GET(request(false), params)).status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
it("preserves an invitation access refusal", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
  expect((await GET(request(), params)).status).toBe(404);
});
it("refuses non-image content", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("<script>", { headers: { "content-type": "text/html" } })),
  );
  expect((await GET(request(), params)).status).toBe(502);
});
it("reports an unavailable backend", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Offline")));
  expect((await GET(request(), params)).status).toBe(500);
});
