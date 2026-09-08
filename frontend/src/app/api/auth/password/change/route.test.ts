/**
 * @vitest-environment node
 *
 * A server route: it reads the access-token cookie and forwards the change to
 * the backend. The token lives in an HttpOnly cookie, so what this proves is that
 * the proxy carries it as a bearer and passes the backend's answer straight back.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as changePassword } from "./route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request(cookies: Record<string, string> = {}, body: unknown = {}): NextRequest {
  const header = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest("http://localhost:3000/api/auth/password/change", {
    method: "POST",
    headers: { ...(header ? { cookie: header } : {}), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("changing a password", () => {
  it("forwards the access-token cookie as a bearer and answers 204", async () => {
    vi.mocked(backendFetch).mockResolvedValue(null);

    const response = await changePassword(
      request({ access_token: "tok-123" }, { current_password: "old", new_password: "newpass12" }),
    );

    expect(response.status).toBe(204);
    const [endpoint, options] = vi.mocked(backendFetch).mock.calls[0]!;
    expect(endpoint).toBe("/api/v1/auth/password/change");
    expect((options?.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("sends no bearer when the browser carries no token, so the backend refuses it", async () => {
    vi.mocked(backendFetch).mockResolvedValue(null);

    await changePassword(request({}, { current_password: "old", new_password: "newpass12" }));

    const [, options] = vi.mocked(backendFetch).mock.calls[0]!;
    expect((options?.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("passes the backend's refusal body and status straight through", async () => {
    const body = {
      error: { code: "AUTHENTICATION_ERROR", message: "Current password is incorrect" },
    };
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", body));

    const response = await changePassword(request({ access_token: "t" }));

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual(body);
  });

  it("forwards a rate limit as a rate limit", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(429, "Too Many Requests", null));

    const response = await changePassword(request({ access_token: "t" }));

    expect(response.status).toBe(429);
  });

  it("answers a non-backend failure as a 500 refusal", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("socket hang up"));

    const response = await changePassword(request({ access_token: "t" }));

    expect(response.status).toBe(500);
  });
});
