import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as personal from "../app/api/me/connected-accounts/[[...path]]/route";
import * as organization from "../app/api/connected-accounts/[[...path]]/route";

import { ACCESS_TOKEN_COOKIE } from "./session-cookie";

afterEach(() => vi.unstubAllGlobals());

describe.each([
  { path: "/api/me/connected-accounts", handlers: personal },
  { path: "/api/connected-accounts", handlers: organization },
])("connected-account proxy $path", ({ path, handlers }) => {
  it("exposes only listing and removal, leaving OAuth consent to its dedicated route", () => {
    expect(Object.keys(handlers).sort()).toEqual(["DELETE", "GET"]);
  });

  it.each(["GET", "DELETE"] as const)("requires authentication for %s", async (method) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const response = await handlers[method](
      new NextRequest(`http://localhost:3000${path}`, { method }),
    );
    expect(response.status).toBe(401);
    expect(upstream).not.toHaveBeenCalled();
  });

  it.each(["GET", "DELETE"] as const)(
    "forwards %s with the session and active organization",
    async (method) => {
      const suffix = method === "GET" ? "?limit=10" : "/account-1";
      const status = method === "GET" ? 200 : 204;
      const upstream = vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response(method === "GET" ? '{"items":[]}' : null, { status }));
      vi.stubGlobal("fetch", upstream);
      const response = await handlers[method](
        new NextRequest(`http://localhost:3000${path}${suffix}`, {
          method,
          headers: { cookie: `${ACCESS_TOKEN_COOKIE}=access`, "X-Organization-Id": "org-1" },
        }),
      );
      const [url, init] = upstream.mock.calls[0]!;
      expect(url).toBe(`http://localhost:8000/api/v1${path.slice(4)}${suffix}`);
      expect(init?.method).toBe(method);
      expect(new Headers(init?.headers).get("authorization")).toBe("Bearer access");
      expect(new Headers(init?.headers).get("X-Organization-Id")).toBe("org-1");
      expect(init?.cache).toBe("no-store");
      expect(response.status).toBe(status);
    },
  );

  it("preserves backend permission refusals", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response('{"detail":"forbidden"}', { status: 403 })),
    );
    const response = await handlers.GET(
      new NextRequest(`http://localhost:3000${path}`, {
        headers: { cookie: `${ACCESS_TOKEN_COOKIE}=access` },
      }),
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "forbidden" });
  });
});
