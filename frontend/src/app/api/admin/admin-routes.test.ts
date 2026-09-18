/**
 * @vitest-environment node
 *
 * These are server routes. The suite's default environment is jsdom, where
 * running route handlers in a browser-shaped global is a lie about where they
 * execute.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as impersonate } from "./users/[userId]/impersonate/route";
import { requireAdmin } from "@/lib/admin-auth";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/admin-auth", () => ({ requireAdmin: vi.fn() }));
vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request(url = "http://localhost:3000/api/admin/users/u-1/impersonate"): NextRequest {
  return new NextRequest(url);
}

const user = { params: Promise.resolve({ userId: "u-1" }) };

/** The path the route forwarded to. */
function forwarded(): string {
  return vi.mocked(backendFetch).mock.calls[0]![0] as string;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(requireAdmin).mockResolvedValue({ accessToken: "at" });
  vi.mocked(backendFetch).mockResolvedValue({ access_token: "imp", expires_in: 3600 });
});

/**
 * The one deployment-admin route that is still hand-rolled.
 *
 * The plain admin forwarders now go through `platformProxy`, where the backend's
 * own `CurrentAppAdmin` is the gate. Impersonation stays here because it mints an
 * access token into an HttpOnly cookie rather than answering with a body - so it
 * asks `requireAdmin` first, the same round trip to `/auth/me` every admin route
 * used to make, because the cookie is the only thing the browser controls.
 */
describe("the impersonation route", () => {
  it("refuses when the caller is not an app admin", async () => {
    const refusal = new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 });
    vi.mocked(requireAdmin).mockResolvedValue({
      error: refusal,
    } as unknown as Awaited<ReturnType<typeof requireAdmin>>);

    const response = await impersonate(request(), user);

    expect(response.status).toBe(403);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("forwards with the admin's own token", async () => {
    await impersonate(request(), user);

    expect(forwarded()).toBe("/api/v1/admin/users/u-1/impersonate");
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      method: "POST",
      headers: expect.objectContaining({ Authorization: "Bearer at" }),
    });
  });

  it("answers 500 when it could not be forwarded", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await impersonate(request(), user);

    expect(response.status).toBe(500);
  });

  it("passes the backend's own refusal through", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(409, "Conflict", null));

    const response = await impersonate(request(), user);

    expect(response.status).toBe(409);
  });

  it("starts an impersonation by swapping the access cookie, and hands back no token", async () => {
    // The most privileged action in the product: the token goes where every other
    // access token lives, an HttpOnly cookie, and never into a response body a
    // page could copy somewhere (#1044).
    vi.mocked(backendFetch).mockResolvedValue({
      access_token: "imp",
      token_type: "bearer",
      impersonated_user_id: "u-1",
      impersonated_by: "a-1",
      expires_in: 3600,
      expires_at: "2026-09-05T11:00:00Z",
      session_id: "s-1",
    });

    const response = await impersonate(request(), user);

    const body = await response.json();
    expect(body).toMatchObject({ impersonated_user_id: "u-1", session_id: "s-1" });
    expect(body).not.toHaveProperty("access_token");
    const cookie = response.headers
      .getSetCookie()
      .find((entry) => entry.startsWith("access_token="));
    expect(cookie).toContain("access_token=imp");
    expect(cookie).toContain("HttpOnly");
    // Five minutes past the token, so an expired impersonation is still in the
    // jar when the refresh route decides what the browser was doing.
    expect(cookie).toContain("Max-Age=3900");
  });

  it("leaves the administrator's refresh cookie alone", async () => {
    // It is what the next `/api/auth/me` refreshes from once the impersonation
    // has ended, so ending one never means signing in again.
    const response = await impersonate(request(), user);

    expect(
      response.headers.getSetCookie().some((entry) => entry.startsWith("refresh_token=")),
    ).toBe(false);
  });
});
