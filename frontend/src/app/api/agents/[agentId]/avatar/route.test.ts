/** @vitest-environment node */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./route";

function request(query = "", signedIn = true) {
  const req = new NextRequest(`http://localhost:3000/api/agents/agent/avatar${query}`);
  if (signedIn) req.cookies.set("agenticos_access_token", "session-token");
  return req;
}

const requestKinds = [
  { name: "a direct NextRequest", wrap: (req: NextRequest) => req },
  {
    name: "a framework-style Request proxy",
    // Next's auto-mode route wrapper reads properties with the target as receiver.
    // Keep native Request internals: Node 24 rejects cloning this Proxy input.
    wrap: (req: NextRequest) =>
      new Proxy(req, {
        get: (target, property) => Reflect.get(target, property, target),
      }),
  },
];

describe.each(requestKinds)("agent avatar image proxy with $name", ({ wrap }) => {
  afterEach(() => vi.unstubAllGlobals());
  it("forwards image bytes with the selected tenant and session", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(new Uint8Array([137, 80, 78, 71]), {
        headers: { "content-type": "image/png" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const req = request("?organization_id=team&v=2");
    req.headers.set("X-Organization-Id", "previous-team");
    const response = await GET(wrap(req));
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents/agent/avatar?organization_id=team&v=2"),
      expect.objectContaining({
        method: "GET",
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
  it("keeps the organization header when the image URL has no override", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("image"));
    vi.stubGlobal("fetch", fetch);
    const req = request();
    req.headers.set("X-Organization-Id", "selected-team");
    const response = await GET(wrap(req));
    expect(response.status).toBe(200);
    expect(await response.text()).toBe("image");
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents/agent/avatar"),
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Organization-Id": "selected-team",
          Authorization: "Bearer session-token",
        }),
      }),
    );
  });
  it("does not contact the backend without a session", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect((await GET(wrap(request("?organization_id=team", false)))).status).toBe(401);
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
    expect((await GET(wrap(request("?organization_id=other-team")))).status).toBe(status);
  });
});

describe("agent avatar upload proxy", () => {
  afterEach(() => vi.unstubAllGlobals());

  function upload(signedIn = true): NextRequest {
    const form = new FormData();
    form.append(
      "file",
      new File([new Uint8Array([137, 80, 78, 71])], "avatar.png", { type: "image/png" }),
    );
    const req = new NextRequest("http://localhost:3000/api/agents/agent/avatar", {
      method: "POST",
      headers: { "X-Organization-Id": "team" },
      body: form,
    });
    if (signedIn) req.cookies.set("agenticos_access_token", "session-token");
    return req;
  }

  it("forwards multipart bytes with the session and organization", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ id: "agent", has_avatar: true }));
    vi.stubGlobal("fetch", fetch);
    const req = upload();
    const contentType = req.headers.get("content-type");
    expect(contentType).toMatch(/^multipart\/form-data; boundary=/);
    const bytes = await req.clone().arrayBuffer();
    const response = await POST(req);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/agents/agent/avatar"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer session-token",
          "X-Organization-Id": "team",
          "Content-Type": contentType,
        }),
        body: bytes,
      }),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: "agent", has_avatar: true });
  });

  it("does not upload without a session", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect((await POST(upload(false))).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([400, 403, 404, 413, 422])("preserves the backend upload refusal %s", async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "refused" }, { status })),
    );
    const response = await POST(upload());
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail: "refused" });
  });
});
