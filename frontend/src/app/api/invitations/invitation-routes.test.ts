/**
 * @vitest-environment node
 *
 * The server routes of the invitation server-side exchange (#1414): staging a
 * token into an httpOnly cookie, closing it after sign-in, and attaching the
 * staged handle to a cross-origin OAuth start. All three are about what crosses
 * the boundary - a handle, never the token - and what the cookie carries; and
 * since every staging names a flow, about the accept redeeming exactly the cookie
 * its flow names.
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

const FLOW = "0123456789abcdef0123456789abcdef";
const OTHER_FLOW = "fedcba9876543210fedcba9876543210";
const stageCookie = (flow: string) => `invitation_stage_${flow}`;

function request(
  cookies: Record<string, string> = {},
  body?: unknown,
  query = "",
  extraHeaders: Record<string, string> = {},
): NextRequest {
  const header = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest(`http://localhost:3000/api/invitations${query}`, {
    method: "POST",
    headers: { ...(header ? { cookie: header } : {}), ...extraHeaders },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

const forFlow = (flow: string) => `?flow=${flow}`;

function cookie(response: Response, name: string) {
  const set = response.headers.getSetCookie().find((entry) => entry.startsWith(`${name}=`));
  if (!set) return undefined;
  const [pair, ...attributes] = set.split("; ");
  return { value: pair!.slice(name.length + 1), attributes: attributes.join("; ") };
}

/** The one staging cookie a response set, whatever flow it was named for. */
function stagedCookie(response: Response) {
  const set = response.headers
    .getSetCookie()
    .filter((entry) => entry.startsWith("invitation_stage_"));
  expect(set).toHaveLength(1);
  const [pair, ...attributes] = set[0]!.split("; ");
  const [name, value] = pair!.split("=");
  return { name: name!, value: value!, attributes: attributes.join("; ") };
}

beforeEach(() => vi.clearAllMocks());

describe("staging a token", () => {
  it("stores the handle in an httpOnly cookie named for the flow, and returns the flow", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce({ handle: "an-opaque-handle" });

    const response = await stage(request({}, { token: "a-live-token" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/invitations/stage", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ token: "a-live-token" }),
    });
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ staged: true, flow: expect.stringMatching(/^[0-9a-f]{32}$/) });
    const set = stagedCookie(response);
    expect(set.name).toBe(stageCookie(body.flow));
    expect(set.value).toBe("an-opaque-handle");
    expect(set.attributes).toContain("HttpOnly");
    expect(set.attributes).toContain("Max-Age=1800");
  });

  it("gives two stagings two cookies, so neither overwrites the other", async () => {
    // A signed-out person opening two invitation links used to stage both into one
    // fixed-name cookie; the second overwrote the first and both pending tabs then
    // redeemed the second invitation.
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ handle: "handle-one" })
      .mockResolvedValueOnce({ handle: "handle-two" });

    const first = stagedCookie(await stage(request({}, { token: "token-one" })));
    const second = stagedCookie(await stage(request({}, { token: "token-two" })));

    expect(first.name).not.toBe(second.name);
    expect(first.value).toBe("handle-one");
    expect(second.value).toBe("handle-two");
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
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("answers 500 when the exchange could not be reached", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("network down"));

    const response = await stage(request({}, { token: "a-live-token" }));

    expect(response.status).toBe(500);
    expect(response.headers.getSetCookie()).toEqual([]);
  });
});

describe("accepting after sign-in", () => {
  const staged = { access_token: "jwt", [stageCookie(FLOW)]: "h" };

  it("refuses without a session", async () => {
    const response = await acceptPending(
      request({ [stageCookie(FLOW)]: "h" }, undefined, forFlow(FLOW)),
    );

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("is a clean miss when no invitation was staged for the flow", async () => {
    const response = await acceptPending(
      request({ access_token: "jwt" }, undefined, forFlow(FLOW)),
    );

    expect(response.status).toBe(404);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("is a clean miss when the landing names no flow, or a malformed one", async () => {
    // Neither shape names a cookie, so neither is read as one - a flow id is only ever
    // 32 hex digits, and anything else must not reach a cookie name.
    expect((await acceptPending(request(staged))).status).toBe(404);
    expect((await acceptPending(request(staged, undefined, "?flow=../access_token"))).status).toBe(
      404,
    );
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("redeems the handle of the flow it was given, and clears exactly that cookie", async () => {
    vi.mocked(backendFetch).mockResolvedValueOnce(undefined);
    const both = { ...staged, [stageCookie(OTHER_FLOW)]: "other" };

    const response = await acceptPending(request(both, undefined, forFlow(FLOW)));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/invitations/staged/accept", {
      method: "POST",
      headers: { Authorization: "Bearer jwt", "X-Invitation-Handle": "h" },
    });
    expect(response.status).toBe(204);
    expect(cookie(response, stageCookie(FLOW))?.value).toBe("");
    expect(cookie(response, stageCookie(OTHER_FLOW))).toBeUndefined();
  });

  it("forwards the caller's address, since the backend rate limits per IP", async () => {
    // Without it every invitee behind the frontend container shares one bucket, and
    // one caller exhausting it locks unrelated invitees out of their acceptance.
    vi.mocked(backendFetch).mockResolvedValueOnce(undefined);

    await acceptPending(
      request(staged, undefined, forFlow(FLOW), { "x-forwarded-for": "203.0.113.7" }),
    );

    expect(backendFetch).toHaveBeenCalledWith(
      "/api/v1/invitations/staged/accept",
      expect.objectContaining({
        headers: expect.objectContaining({ "x-forwarded-for": "203.0.113.7" }),
      }),
    );
  });

  it("clears the spent cookie even when the accept is refused", async () => {
    // The redeem consumed the handle server-side, so the cookie is dead either way;
    // leaving it would only mislead the next attempt.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(400, "Bad Request", {
        detail: "This invitation was sent to a different email address.",
      }),
    );

    const response = await acceptPending(request(staged, undefined, forFlow(FLOW)));

    expect(response.status).toBe(400);
    expect(cookie(response, stageCookie(FLOW))?.value).toBe("");
  });

  it("keeps the cookie on a 401, whose redeem never ran", async () => {
    // A rejected session is refused before the handle is redeemed, so it is unspent;
    // the client refreshes the token and retries, which needs the cookie still there.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(401, "Unauthorized", { detail: "expired" }),
    );

    const response = await acceptPending(
      request({ ...staged, access_token: "stale" }, undefined, forFlow(FLOW)),
    );

    expect(response.status).toBe(401);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("keeps the cookie on a 429, whose redeem never ran either", async () => {
    // The rate limit runs before the redeem, so the handle is unspent - and the 429
    // advertises a retry, which deleting the cookie would turn into a miss.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(429, "Too Many Requests", {
        error: { code: "RATE_LIMIT_EXCEEDED", retry_after_seconds: 30 },
      }),
    );

    const response = await acceptPending(request(staged, undefined, forFlow(FLOW)));

    expect(response.status).toBe(429);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("keeps the cookie on a 5xx, where nothing says whether the redeem ran", async () => {
    // A retry against a handle that was spent answers a miss; a cookie deleted under
    // a handle that was not loses the invitation. The cheaper mistake is kept.
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(503, "Service Unavailable", { detail: "redis down" }),
    );

    const response = await acceptPending(request(staged, undefined, forFlow(FLOW)));

    expect(response.status).toBe(503);
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("answers 500 with the cookie kept when the accept could not be reached", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("network down"));

    const response = await acceptPending(request(staged, undefined, forFlow(FLOW)));

    expect(response.status).toBe(500);
    expect(response.headers.getSetCookie()).toEqual([]);
  });
});

describe("starting an OAuth sign-in", () => {
  const get = (cookies: Record<string, string>, provider: string, query = "") =>
    oauthLogin(request(cookies, undefined, query), { params: Promise.resolve({ provider }) });

  it("attaches the named flow's staged handle to the cross-origin start", async () => {
    const response = await get(
      { [stageCookie(FLOW)]: "h", [stageCookie(OTHER_FLOW)]: "other" },
      "google",
      forFlow(FLOW),
    );

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8000/api/v1/oauth/google/login?invitation_handle=h",
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("carries no handle when none was staged for the flow", async () => {
    const response = await get({ [stageCookie(OTHER_FLOW)]: "other" }, "google", forFlow(FLOW));

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "http://localhost:8000/api/v1/oauth/google/login",
    );
  });

  it("carries no handle when the start names no flow", async () => {
    const response = await get({ [stageCookie(FLOW)]: "h" }, "google");

    expect(response.headers.get("location")).toBe(
      "http://localhost:8000/api/v1/oauth/google/login",
    );
  });

  it("refuses a provider it does not know, rather than build a redirect from it", async () => {
    const response = await get({ [stageCookie(FLOW)]: "h" }, "../evil", forFlow(FLOW));

    expect(response.status).toBe(404);
  });
});
