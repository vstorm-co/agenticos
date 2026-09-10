/**
 * @vitest-environment node
 *
 * The server routes of the invitation server-side exchange (#1414): staging a
 * token into an httpOnly cookie, closing it after sign-in, and attaching the
 * staged handle to a cross-origin OAuth start. All three are about what crosses
 * the boundary - a handle, never the token - and what the cookie carries.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as stage } from "./stage/route";
import { POST as acceptPending } from "./pending/accept/route";
import { GET as oauthLogin } from "../oauth/[provider]/login/route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request(cookies: Record<string, string> = {}, body?: unknown): NextRequest {
  const header = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest("http://localhost:3000/api/invitations", {
    method: "POST",
    headers: header ? { cookie: header } : {},
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

function cookie(response: Response, name: string) {
  const set = response.headers.getSetCookie().find((entry) => entry.startsWith(`${name}=`));
  if (!set) return undefined;
  const [pair, ...attributes] = set.split("; ");
  return { value: pair!.slice(name.length + 1), attributes: attributes.join("; ") };
}

beforeEach(() => vi.clearAllMocks());

describe("staging a token", () => {
  it("stores the handle in an httpOnly cookie and returns nothing else", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce({ handle: "an-opaque-handle" });

    const response = await stage(request({}, { token: "a-live-token" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/invitations/stage", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ token: "a-live-token" }),
    });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ staged: true });
    const set = cookie(response, "invitation_stage");
    expect(set?.value).toBe("an-opaque-handle");
    expect(set?.attributes).toContain("HttpOnly");
    expect(set?.attributes).toContain("Max-Age=1800");
  });

  it("does not put the token or the handle in the reply body", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce({ handle: "an-opaque-handle" });

    const body = await (await stage(request({}, { token: "a-live-token" }))).text();

    expect(body).not.toContain("a-live-token");
    expect(body).not.toContain("an-opaque-handle");
  });

  it("forwards a refused token without setting a cookie", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(404, "Not Found", { detail: "Invitation not found or no longer valid" }),
    );

    const response = await stage(request({}, { token: "forged" }));

    expect(response.status).toBe(404);
    expect(cookie(response, "invitation_stage")).toBeUndefined();
  });

  it("answers 500 when the exchange could not be reached", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("network down"));

    const response = await stage(request({}, { token: "a-live-token" }));

    expect(response.status).toBe(500);
    expect(cookie(response, "invitation_stage")).toBeUndefined();
  });
});

describe("accepting after sign-in", () => {
  it("refuses without a session", async () => {
    const response = await acceptPending(request({ invitation_stage: "h" }));

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("is a clean miss when no invitation was staged", async () => {
    const response = await acceptPending(request({ access_token: "jwt" }));

    expect(response.status).toBe(404);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("redeems the handle from a header and clears the cookie", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce(undefined);

    const response = await acceptPending(request({ access_token: "jwt", invitation_stage: "h" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/invitations/staged/accept", {
      method: "POST",
      headers: { Authorization: "Bearer jwt", "X-Invitation-Handle": "h" },
    });
    expect(response.status).toBe(204);
    expect(cookie(response, "invitation_stage")?.value).toBe("");
  });

  it("clears the spent cookie even when the accept is refused", async () => {
    // The redeem consumed the handle server-side, so the cookie is dead either way;
    // leaving it would only mislead the next attempt.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(400, "Bad Request", {
        detail: "This invitation was sent to a different email address.",
      }),
    );

    const response = await acceptPending(request({ access_token: "jwt", invitation_stage: "h" }));

    expect(response.status).toBe(400);
    expect(cookie(response, "invitation_stage")?.value).toBe("");
  });

  it("answers 500 when the accept could not be reached", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("network down"));

    const response = await acceptPending(request({ access_token: "jwt", invitation_stage: "h" }));

    expect(response.status).toBe(500);
  });

  it("keeps the cookie on a 401, whose redeem never ran", async () => {
    // A rejected session is refused before the handle is redeemed, so it is unspent;
    // the client refreshes the token and retries, which needs the cookie still there.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(401, "Unauthorized", { detail: "expired" }),
    );

    const response = await acceptPending(request({ access_token: "stale", invitation_stage: "h" }));

    expect(response.status).toBe(401);
    // No Set-Cookie for it: the handle was not cleared.
    expect(cookie(response, "invitation_stage")).toBeUndefined();
  });
});

describe("starting an OAuth sign-in", () => {
  const get = (cookies: Record<string, string>, provider: string) =>
    oauthLogin(request(cookies), { params: Promise.resolve({ provider }) });

  it("attaches a staged handle to the cross-origin start", async () => {
    const response = await get({ invitation_stage: "h" }, "google");

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8000/api/v1/oauth/google/login?invitation_handle=h",
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("carries no handle when none was staged", async () => {
    const response = await get({}, "google");

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8000/api/v1/oauth/google/login",
    );
  });

  it("refuses a provider it does not know, rather than build a redirect from it", async () => {
    const response = await get({ invitation_stage: "h" }, "../evil");

    expect(response.status).toBe(404);
  });
});
