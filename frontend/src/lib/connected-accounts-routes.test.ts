import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

import * as organization from "../app/api/connected-accounts/[[...path]]/route";
import * as personal from "../app/api/me/connected-accounts/[[...path]]/route";

afterEach(() => vi.unstubAllGlobals());

it.each([
  { prefix: "/connected-accounts", handlers: organization },
  { prefix: "/me/connected-accounts", handlers: personal },
])(
  "lists and disconnects $prefix through the authenticated proxy",
  async ({ prefix, handlers }) => {
    const fetch = vi
      .fn()
      .mockImplementation(async (_url: string, init: RequestInit) =>
        init.method === "DELETE"
          ? new Response(null, { status: 204 })
          : Response.json({ items: [{ id: "account-1" }], total: 1 }),
      );
    vi.stubGlobal("fetch", fetch);
    const request = (suffix = "", method = "GET") => {
      const req = new NextRequest(`http://localhost:3000/api${prefix}${suffix}`, {
        method,
        headers: { "X-Organization-Id": "org-1" },
      });
      req.cookies.set("agenticos_access_token", "session-token");
      return req;
    };
    const listed = await handlers.GET(request());
    expect(listed.status).toBe(200);
    expect(await listed.json()).toEqual({ items: [{ id: "account-1" }], total: 1 });
    expect(listed.headers.get("cache-control")).toBe("no-store");
    expect(fetch).toHaveBeenLastCalledWith(
      `http://localhost:8000/api/v1${prefix}`,
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: "Bearer session-token",
          "X-Organization-Id": "org-1",
        }),
      }),
    );
    const removed = await handlers.DELETE(request("/account-1", "DELETE"));
    expect(removed.status).toBe(204);
    expect(fetch).toHaveBeenLastCalledWith(
      `http://localhost:8000/api/v1${prefix}/account-1`,
      expect.objectContaining({ method: "DELETE" }),
    );
  },
);

it.each([personal, organization])("requires a session for account reads", async (handlers) => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const response = await handlers.GET(
    new NextRequest("http://localhost:3000/api/connected-accounts"),
  );
  expect(response.status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
