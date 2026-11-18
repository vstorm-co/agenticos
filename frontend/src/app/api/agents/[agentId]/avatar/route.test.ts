/** @vitest-environment node */
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "./route";

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
