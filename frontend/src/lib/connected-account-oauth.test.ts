import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { POST as personalStart } from "../app/api/me/connected-accounts/oauth/start/route";
import { POST as organizationStart } from "../app/api/connected-accounts/oauth/start/route";

import { ACCESS_TOKEN_COOKIE } from "./session-cookie";
import { ACCOUNT_OAUTH_COOKIE, startConnectedAccountOAuth } from "./connected-account-oauth";

afterEach(() => vi.unstubAllGlobals());

describe("connected-account consent", () => {
  it.each(["/api/me/connected-accounts/oauth/start", "/api/connected-accounts/oauth/start"])(
    "binds %s to an HttpOnly nonce without losing the organization",
    async (path) => {
      const upstream = vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ authorization_url: "https://accounts.google.com/consent" }), {
          headers: { "content-type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", upstream);
      const start = path.includes("/me/") ? personalStart : organizationStart;
      const response = await start(
        new NextRequest(`http://localhost:3000${path}`, {
          method: "POST",
          headers: { cookie: `${ACCESS_TOKEN_COOKIE}=access`, "X-Organization-Id": "org-1" },
        }),
      );
      expect(response.status).toBe(200);
      const call = upstream.mock.calls[0];
      if (!call) throw new Error("Expected a consent request");
      const init = call[1];
      const headers = new Headers(init?.headers);
      expect(headers.get("authorization")).toBe("Bearer access");
      expect(headers.get("X-Organization-Id")).toBe("org-1");
      const raw = init?.body;
      if (!(raw instanceof ArrayBuffer)) throw new Error("Expected a buffered request body");
      const body: unknown = JSON.parse(new TextDecoder().decode(raw));
      if (body === null || typeof body !== "object" || !("browser_nonce" in body))
        throw new Error("Expected a consent nonce");
      expect(body.browser_nonce).toMatch(/^[A-Za-z0-9_-]{43}$/);
      const cookie = response.headers.get("set-cookie");
      expect(cookie).toContain(`${ACCOUNT_OAUTH_COOKIE}=${body.browser_nonce}`);
      expect(cookie).toContain("HttpOnly");
      expect(cookie).toContain("SameSite=lax");
      expect(cookie).toContain("Path=/api/me/mcp-connections/oauth/callback");
      expect(response.headers.get("cache-control")).toBe("no-store");
    },
  );

  it("does not issue a consent cookie after a refused start", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(new Response("{}", { status: 403 })),
    );
    const response = await startConnectedAccountOAuth(
      new NextRequest("http://localhost:3000/api/me/connected-accounts/oauth/start", {
        method: "POST",
        headers: { cookie: `${ACCESS_TOKEN_COOKIE}=access` },
      }),
    );
    expect(response.status).toBe(403);
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
