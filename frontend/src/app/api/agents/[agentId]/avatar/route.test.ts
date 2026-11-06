/** @vitest-environment node */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

function request(query = "", signedIn = true) {
  const req = new NextRequest(`http://localhost:3000/api/agents/agent/avatar${query}`);
  if (signedIn) req.cookies.set("agenticos_access_token", "session-token");
  return req;
}

describe("agent avatar image proxy", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("forwards image bytes with the selected tenant and session", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([137, 80, 78, 71]), {
        headers: { "content-type": "image/png" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const response = await GET(request("?organization_id=team&v=2"));
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents/agent/avatar?organization_id=team&v=2"),
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Organization-Id": "team",
          Authorization: "Bearer session-token",
        }),
      }),
    );
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([137, 80, 78, 71]));
  });
  it("does not contact the backend without a session", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect((await GET(request("?organization_id=team", false))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it.each([403, 404])("preserves the backend's access refusal %s", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('{"detail":"refused"}', {
          status,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    expect((await GET(request("?organization_id=other-team"))).status).toBe(status);
  });
});
