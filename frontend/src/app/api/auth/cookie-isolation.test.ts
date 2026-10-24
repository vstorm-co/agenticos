/** @vitest-environment node */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as login } from "./login/route";
import { POST as ldapLogin } from "./ldap/login/route";
import { POST as magicLinkVerify } from "./magic-link/verify/route";
import { POST as oauthCallback } from "./oauth-callback/route";
import { POST as changePassword } from "./password/change/route";
import { POST as logout } from "./logout/route";
import { GET as me } from "./me/route";
import { POST as refresh } from "./refresh/route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

const OTHER_APP = { access_token: "other-access", refresh_token: "other-refresh" };
const AGENTICOS = {
  agenticos_access_token: "our-access",
  agenticos_refresh_token: "our-refresh",
};

function request(cookies: Record<string, string>, body: unknown = {}): NextRequest {
  return new NextRequest("http://localhost:3000/api/auth", {
    method: "POST",
    headers: {
      cookie: Object.entries(cookies)
        .map(([name, value]) => `${name}=${value}`)
        .join("; "),
    },
    body: JSON.stringify(body),
  });
}

function cookieNames(response: Response): string[] {
  return response.headers.getSetCookie().map((header) => header.split("=", 1)[0]!);
}

beforeEach(() => vi.resetAllMocks());

describe("cookies shared with another app on the same hostname", () => {
  it.each([
    ["password login", login, { email: "a@example.com", password: "secret" }],
    ["directory login", ldapLogin, { username: "ada", password: "secret" }],
    ["magic link", magicLinkVerify, { token: "one-time" }],
    ["OAuth callback", oauthCallback, { code: "one-time" }],
  ] as const)("%s sets only AgenticOS cookies", async (_name, handler, credentials) => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "fresh-access", refresh_token: "fresh-refresh" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await handler(request(OTHER_APP, credentials));

    expect(response.status).toBe(200);
    expect(cookieNames(response)).toEqual(["agenticos_access_token", "agenticos_refresh_token"]);
    await expect(response.json()).resolves.toMatchObject({ access_token: "fresh-access" });
  });

  it("password changes replace only AgenticOS cookies", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh", refresh_token: "fresh-rt" });

    const response = await changePassword(
      request({ ...OTHER_APP, ...AGENTICOS }, { current_password: "old", new_password: "new" }),
    );

    expect(response.status).toBe(200);
    expect(cookieNames(response)).toEqual(["agenticos_access_token", "agenticos_refresh_token"]);
    expect(backendFetch).toHaveBeenCalledWith(
      "/api/v1/auth/password/change",
      expect.objectContaining({ headers: { Authorization: "Bearer our-access" } }),
    );
  });

  it.each([
    ["session lookup", me],
    ["refresh", refresh],
  ] as const)("%s ignores another app's cookies", async (_name, handler) => {
    const response = await handler(request(OTHER_APP));

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
    expect(cookieNames(response)).toEqual([]);
  });

  it("session lookup forwards only the AgenticOS access token when both are present", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-1" });

    const response = await me(request({ ...OTHER_APP, ...AGENTICOS }));

    expect(response.status).toBe(200);
    expect(backendFetch).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/me", {
      headers: { Authorization: "Bearer our-access" },
    });
  });

  it("refresh forwards only the AgenticOS refresh token and keeps API field names", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh", refresh_token: "fresh-rt" });

    const response = await refresh(request({ ...OTHER_APP, ...AGENTICOS }));

    expect(response.status).toBe(200);
    expect(backendFetch).toHaveBeenCalledExactlyOnceWith("/api/v1/auth/refresh", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ refresh_token: "our-refresh" }),
    });
    expect(cookieNames(response)).toEqual(["agenticos_access_token", "agenticos_refresh_token"]);
  });

  it.each([
    ["session lookup", me],
    ["refresh", refresh],
    ["logout", logout],
  ] as const)("%s clears only AgenticOS cookies after a refusal", async (_name, handler) => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", null));

    const response = await handler(request({ ...OTHER_APP, ...AGENTICOS }));

    expect(cookieNames(response)).toEqual(["agenticos_access_token", "agenticos_refresh_token"]);
    for (const cookie of response.headers.getSetCookie()) {
      expect(cookie).toContain("Max-Age=0");
    }
  });

  it("logout does not forward another app's refresh token", async () => {
    const response = await logout(request(OTHER_APP));

    expect(response.status).toBe(200);
    expect(backendFetch).not.toHaveBeenCalled();
    expect(cookieNames(response)).toEqual(["agenticos_access_token", "agenticos_refresh_token"]);
  });
});
