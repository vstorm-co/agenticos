/**
 * @vitest-environment node
 *
 * A server route, in the environment it actually runs in.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as ldapLogin } from "./route";
import { stageCookieName } from "@/lib/invitation-links";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

const FLOW = "0123456789abcdef0123456789abcdef";

function request(body: unknown, { query = "", cookie = "" } = {}): NextRequest {
  return new NextRequest(`http://localhost:3000/api/auth/ldap/login${query}`, {
    method: "POST",
    headers: cookie ? { cookie } : {},
    body: JSON.stringify(body),
  });
}

/** The cookie the response sets, by name - `undefined` when it sets none. */
function cookie(response: Response, name: string): string | undefined {
  return response.headers.getSetCookie().find((entry) => entry.startsWith(`${name}=`));
}

const CREDENTIALS = { username: "jdoe", password: "secret" };

beforeEach(() => vi.clearAllMocks());

describe("signing in with a directory account", () => {
  it("posts the username as JSON, not the OAuth2 form the password login takes", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await ldapLogin(request(CREDENTIALS));

    expect(backendFetch).toHaveBeenNthCalledWith(1, "/api/v1/auth/ldap/login", {
      method: "POST",
      headers: {},
      body: JSON.stringify(CREDENTIALS),
    });
    expect(backendFetch).toHaveBeenNthCalledWith(2, "/api/v1/auth/me", {
      headers: { Authorization: "Bearer at" },
    });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ user: { id: "u-1" }, access_token: "at" });
  });

  it("stores both tokens where no script can read them", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await ldapLogin(request(CREDENTIALS));

    expect(cookie(response, "access_token")).toMatch(/^access_token=at;.*HttpOnly/);
    expect(cookie(response, "access_token")).toContain("Max-Age=900");
    expect(cookie(response, "refresh_token")).toMatch(/^refresh_token=rt;.*HttpOnly/);
    expect(cookie(response, "refresh_token")).toContain("Max-Age=604800");
  });

  it("attaches the named flow's staged invitation, which the browser cannot read", async () => {
    // A directory account is created on its first sign-in, so an invite-only
    // deployment admits it on the invitation the way it admits a registration.
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    await ldapLogin(
      request(
        { ...CREDENTIALS, invitation_handle: "forged" },
        { query: `?flow=${FLOW}`, cookie: `${stageCookieName(FLOW)}=h-1` },
      ),
    );

    expect(vi.mocked(backendFetch).mock.calls[0]?.[1]?.body).toBe(
      JSON.stringify({ ...CREDENTIALS, invitation_handle: "h-1" }),
    );
  });

  it("carries no handle when the flow staged none", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    await ldapLogin(request(CREDENTIALS, { query: `?flow=${FLOW}` }));

    expect(vi.mocked(backendFetch).mock.calls[0]?.[1]?.body).toBe(JSON.stringify(CREDENTIALS));
  });

  it("passes the directory's refusal through, envelope and status", async () => {
    const envelope = {
      error: { code: "DIRECTORY_CREDENTIALS_REJECTED", message: "Invalid username or password" },
    };
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", envelope));

    const response = await ldapLogin(request(CREDENTIALS));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual(envelope);
    expect(cookie(response, "access_token")).toBeUndefined();
  });

  it("says login failed when the refusal carried no body", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(503, "Unavailable", null));

    const response = await ldapLogin(request(CREDENTIALS));

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
  });

  it("forwards a rate limit with its wait", async () => {
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(
        429,
        "Too Many Requests",
        { error: { code: "RATE_LIMIT_EXCEEDED" } },
        new Headers({ "retry-after": "30" }),
      ),
    );

    const response = await ldapLogin(request(CREDENTIALS));

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
  });

  it("answers 500 for a failure that is not the backend refusing", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await ldapLogin(request(CREDENTIALS));

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({ code: "INTERNAL_SERVER_ERROR" });
  });
});
