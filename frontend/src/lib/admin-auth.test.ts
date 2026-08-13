import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { requireAdmin } from "./admin-auth";
import { backendFetch } from "./server-api";

// The real `bffRefusal` stays: the refusals under test are the responses it mints.
vi.mock("./server-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./server-api")>()),
  backendFetch: vi.fn(),
}));

/**
 * The gate on every `/api/admin/*` route.
 *
 * It asks the backend who the caller is rather than trusting anything in the
 * request, because the cookie is the only thing the browser controls and
 * `is_app_admin` is the flag the backend itself gates on. Two failures have to
 * look different to the caller and identical to an attacker: no session at all is
 * 401, and a session without the flag is 403.
 */
function request(cookie?: string): NextRequest {
  const headers: Record<string, string> = cookie ? { cookie: `access_token=${cookie}` } : {};
  return new NextRequest("http://localhost:3000/api/admin/users", { headers });
}

beforeEach(() => vi.clearAllMocks());

describe("requireAdmin", () => {
  it("hands back the token for an app admin, which the route then forwards", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ is_app_admin: true });

    const result = await requireAdmin(request("t-1"));

    expect(result).toEqual({ accessToken: "t-1" });
    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/me", {
      headers: { Authorization: "Bearer t-1" },
    });
  });

  it("refuses an unauthenticated request without asking the backend", async () => {
    const result = await requireAdmin(request());

    expect(backendFetch).not.toHaveBeenCalled();
    expect("error" in result && result.error.status).toBe(401);
  });

  it("refuses a signed-in user who is not an app admin", async () => {
    // 403 rather than 401: they are who they say they are, and this is not theirs.
    vi.mocked(backendFetch).mockResolvedValue({ is_app_admin: false });

    const result = await requireAdmin(request("t-1"));

    expect("error" in result && result.error.status).toBe(403);
  });

  it("refuses a user whose record does not carry the flag at all", async () => {
    // An older token or a slimmed-down response; absent has to mean "not an
    // admin" rather than `undefined === true`.
    vi.mocked(backendFetch).mockResolvedValue({});

    const result = await requireAdmin(request("t-1"));

    expect("error" in result && result.error.status).toBe(403);
  });

  it("treats a token the backend rejects as no session", async () => {
    // An expired cookie reaches here as a failed `/auth/me`; answering 403 would
    // tell somebody their expired session was merely underprivileged.
    vi.mocked(backendFetch).mockRejectedValue(new Error("401"));

    const result = await requireAdmin(request("t-expired"));

    expect("error" in result && result.error.status).toBe(401);
  });
});
