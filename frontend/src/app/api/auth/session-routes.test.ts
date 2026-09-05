/**
 * @vitest-environment node
 *
 * These are server routes. The suite's default environment is jsdom, where
 * `request.formData()` never resolves - the multipart parser wants a real
 * stream - and running route handlers in a browser-shaped global is a lie about
 * where they execute anyway.
 */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { POST as login } from "./login/route";
import { POST as magicLinkRequest } from "./magic-link/request/route";
import { POST as magicLinkVerify } from "./magic-link/verify/route";
import { POST as oauthCallback } from "./oauth-callback/route";
import { POST as passwordResetConfirm } from "./password-reset/confirm/route";
import { POST as passwordResetRequest } from "./password-reset/request/route";
import { POST as register } from "./register/route";
import { DELETE as endImpersonation } from "./impersonation/route";
import { POST as logout } from "./logout/route";
import { GET as me } from "./me/route";
import { POST as refresh } from "./refresh/route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

/** A request carrying whatever cookies the browser would have, and optionally the
 * `x-forwarded-for` a proxy in front of the frontend would add. */
function request(
  cookies: Record<string, string> = {},
  body?: unknown,
  extraHeaders: Record<string, string> = {},
): NextRequest {
  const header = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest("http://localhost:3000/api/auth", {
    method: "POST",
    headers: { ...(header ? { cookie: header } : {}), ...extraHeaders },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

/** The cookie the response sets, by name - `undefined` when it sets none. */
function cookie(response: Response, name: string) {
  const set = response.headers.getSetCookie().find((entry) => entry.startsWith(`${name}=`));
  if (!set) return undefined;
  const [pair, ...attributes] = set.split("; ");
  return {
    value: pair!.slice(name.length + 1),
    attributes: attributes.join("; "),
  };
}

beforeEach(() => vi.clearAllMocks());

/**
 * The four routes that own the session.
 *
 * Everything here is about the cookies. The tokens live in HttpOnly cookies so
 * no script can read them, which is also why the access token is echoed in the
 * *body* - the chat's websocket authenticates with it through
 * `Sec-WebSocket-Protocol`, and it has no other way to get one.
 *
 * The refusals matter as much as the successes: the backend's own status and
 * `detail` have to survive the hop, because "incorrect email or password" and
 * "something broke" send somebody to different places. And a session that
 * cannot be recovered has to clear its cookies rather than leave a browser
 * retrying a credential the server has already refused.
 */
describe("signing in", () => {
  it("hands the backend a form, because that is what OAuth2 password flow takes", async () => {
    // Not JSON: FastAPI's token endpoint reads `username` and `password` from a
    // form body, and posting JSON there answers 422.
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1", email: "kacper@example.com" });

    await login(request({}, { email: "kacper@example.com", password: "secret" }));

    expect(backendFetch).toHaveBeenNthCalledWith(1, "/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "username=kacper%40example.com&password=secret",
    });
  });

  it("answers with the user, and the token the websocket needs", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1", email: "kacper@example.com" });

    const response = await login(request({}, { email: "kacper@example.com", password: "s" }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      user: { id: "u-1" },
      access_token: "at",
    });
    expect(backendFetch).toHaveBeenNthCalledWith(2, "/api/v1/auth/me", {
      headers: { Authorization: "Bearer at" },
    });
  });

  it("stores both tokens where no script can read them", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await login(request({}, { email: "a@example.com", password: "s" }));

    expect(cookie(response, "access_token")).toMatchObject({ value: "at" });
    expect(cookie(response, "access_token")?.attributes).toContain("HttpOnly");
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=900");
    expect(cookie(response, "refresh_token")).toMatchObject({ value: "rt" });
    expect(cookie(response, "refresh_token")?.attributes).toContain("Max-Age=604800");
  });

  it("passes the backend's refusal through, status and sentence", async () => {
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(401, "Unauthorized", { detail: "Incorrect email or password" }),
    );

    const response = await login(request({}, { email: "a@example.com", password: "wrong" }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ detail: "Incorrect email or password" });
    expect(cookie(response, "access_token")).toBeUndefined();
  });

  it("says login failed when the refusal named no reason", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(400, "Bad Request", null));

    const response = await login(request({}, { email: "a@example.com", password: "x" }));

    await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
  });

  it("answers 500 for a failure that is not the backend refusing", async () => {
    // An unreachable backend, or a body this route could not parse.
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await login(request({}, { email: "a@example.com", password: "x" }));

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({ code: "INTERNAL_SERVER_ERROR" });
  });
});

describe("signing out", () => {
  it("invalidates the refresh token server-side and clears both cookies", async () => {
    vi.mocked(backendFetch).mockResolvedValue({});

    const response = await logout(request({ refresh_token: "rt" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/logout", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ refresh_token: "rt" }),
    });
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    expect(cookie(response, "refresh_token")?.attributes).toContain("Max-Age=0");
  });

  it("clears the cookies even when the server could not be told", async () => {
    // An expired token answers 401 here, and leaving somebody signed in locally
    // is the worse outcome.
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", null));

    const response = await logout(request({ refresh_token: "rt" }));

    expect(response.status).toBe(200);
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
  });

  it("logs an unexpected failure rather than swallowing it silently", async () => {
    // A refused logout is routine; an unreachable backend is worth a line in the
    // server log.
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await logout(request({ refresh_token: "rt" }));

    expect(logged).toHaveBeenCalled();
    expect(cookie(response, "refresh_token")?.attributes).toContain("Max-Age=0");
    logged.mockRestore();
  });

  it("clears the cookies for somebody who had no session to end", async () => {
    const response = await logout(request());

    expect(backendFetch).not.toHaveBeenCalled();
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
  });
});

describe("refreshing the token", () => {
  it("mints an access token and stores it", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh" });

    const response = await refresh(request({ refresh_token: "rt" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/refresh", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ refresh_token: "rt" }),
    });
    await expect(response.json()).resolves.toMatchObject({ access_token: "fresh" });
    expect(cookie(response, "access_token")).toMatchObject({ value: "fresh" });
  });

  it("rotates the refresh token when the backend issues a new one", async () => {
    // A rotating refresh token is only rotated if the new one is actually stored.
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh", refresh_token: "rt-2" });

    const response = await refresh(request({ refresh_token: "rt-1" }));

    expect(cookie(response, "refresh_token")).toMatchObject({ value: "rt-2" });
  });

  it("leaves the refresh cookie alone when the backend kept the old one", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh" });

    const response = await refresh(request({ refresh_token: "rt-1" }));

    expect(cookie(response, "refresh_token")).toBeUndefined();
  });

  it("refuses without asking the backend when there is no refresh cookie", async () => {
    const response = await refresh(request());

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("clears both cookies when the refresh token is no longer accepted", async () => {
    // Otherwise the browser retries a credential the server has already refused,
    // on every request, until somebody clears their storage by hand.
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", null));

    const response = await refresh(request({ refresh_token: "stale" }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ code: "SESSION_EXPIRED" });
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    expect(cookie(response, "refresh_token")?.attributes).toContain("Max-Age=0");
  });

  it("keeps the session when the failure was not a refusal", async () => {
    // A 500 from an unreachable backend is not a reason to sign somebody out.
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await refresh(request({ refresh_token: "rt" }));

    expect(response.status).toBe(500);
    expect(cookie(response, "access_token")).toBeUndefined();
  });

  it("refuses to mint the administrator's token under an impersonation cookie", async () => {
    // The refresh cookie is the administrator's own; the access cookie says the
    // browser was acting as somebody else. Refreshing here would answer a request
    // the page made as the target with the administrator's token, and the client
    // would replay it as them (#1044). The impersonation is over instead: its
    // cookie goes, the refresh cookie stays, and the client is told which it was.
    const impersonation = `h.${Buffer.from(JSON.stringify({ sub: "u-1", act: "a-1" })).toString("base64url")}.s`;

    const response = await refresh(request({ access_token: impersonation, refresh_token: "rt" }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ code: "IMPERSONATION_ENDED" });
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    expect(cookie(response, "refresh_token")).toBeUndefined();
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("refreshes an ordinary expired access token as before", async () => {
    const ordinary = `h.${Buffer.from(JSON.stringify({ sub: "u-1" })).toString("base64url")}.s`;
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "fresh" });

    const response = await refresh(request({ access_token: ordinary, refresh_token: "rt" }));

    expect(response.status).toBe(200);
    expect(cookie(response, "access_token")).toMatchObject({ value: "fresh" });
  });
});

describe("reading the session", () => {
  function get(cookies: Record<string, string> = {}) {
    const header = Object.entries(cookies)
      .map(([name, value]) => `${name}=${value}`)
      .join("; ");
    return me(
      new NextRequest("http://localhost:3000/api/auth/me", {
        headers: header ? { cookie: header } : {},
      }),
    );
  }

  it("answers with the user and echoes the token the socket needs", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-1", email: "kacper@example.com" });

    const response = await get({ access_token: "at" });

    await expect(response.json()).resolves.toMatchObject({ id: "u-1", access_token: "at" });
  });

  it("refreshes transparently when the access cookie has expired", async () => {
    // The access cookie lasts fifteen minutes and the refresh one lasts a week:
    // a reload after lunch has to keep the session, and the chat socket with it.
    vi.mocked(backendFetch)
      .mockRejectedValueOnce(new BackendApiError(401, "Unauthorized", null))
      .mockResolvedValueOnce({ access_token: "fresh", refresh_token: "rt-2" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await get({ access_token: "stale", refresh_token: "rt-1" });

    await expect(response.json()).resolves.toMatchObject({ id: "u-1", access_token: "fresh" });
    expect(cookie(response, "access_token")).toMatchObject({ value: "fresh" });
    expect(cookie(response, "refresh_token")).toMatchObject({ value: "rt-2" });
  });

  it("stores only the access token when the refresh one was not rotated", async () => {
    vi.mocked(backendFetch)
      .mockRejectedValueOnce(new BackendApiError(401, "Unauthorized", null))
      .mockResolvedValueOnce({ access_token: "fresh" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await get({ access_token: "stale", refresh_token: "rt-1" });

    expect(cookie(response, "refresh_token")).toBeUndefined();
  });

  it("refreshes for somebody who has only the long-lived cookie left", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "fresh" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await get({ refresh_token: "rt" });

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ access_token: "fresh" });
  });

  it("passes a refusal that is not about the token through as it stands", async () => {
    // A deactivated account answers 403, and refreshing would not help.
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(403, "Forbidden", { detail: "Inactive user" }),
    );

    const response = await get({ access_token: "at", refresh_token: "rt" });

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toEqual({ code: "FAILED_TO_GET_USER" });
  });

  it("answers 500 when the backend could not be reached at all", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await get({ access_token: "at" });

    expect(response.status).toBe(500);
  });

  it("refuses somebody with no cookies at all", async () => {
    const response = await get();

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("clears the cookies when the refresh fails, because the session is over", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", null));

    const response = await get({ refresh_token: "stale" });

    expect(response.status).toBe(401);
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    expect(cookie(response, "refresh_token")?.attributes).toContain("Max-Age=0");
  });
});

describe("ending an impersonation", () => {
  function end(cookies: Record<string, string> = {}) {
    const header = Object.entries(cookies)
      .map(([name, value]) => `${name}=${value}`)
      .join("; ");
    return endImpersonation(
      new NextRequest("http://localhost:3000/api/auth/impersonation", {
        method: "DELETE",
        headers: header ? { cookie: header } : {},
      }),
    );
  }

  it("tells the backend with the impersonation's own token, then drops the cookie", async () => {
    // The order matters: the backend closes the session row and audits the end;
    // the cookie is what the impersonation lives in on this side. The refresh
    // cookie is the administrator's own and is not touched (#1044).
    vi.mocked(backendFetch).mockResolvedValue(null);

    const response = await end({ access_token: "imp", refresh_token: "admin-rt" });

    expect(response.status).toBe(200);
    expect(backendFetch).toHaveBeenCalledWith(
      "/api/v1/auth/impersonation",
      expect.objectContaining({
        method: "DELETE",
        headers: { Authorization: "Bearer imp" },
      }),
    );
    expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    expect(cookie(response, "refresh_token")).toBeUndefined();
  });

  it.each([400, 401])(
    "drops the cookie when the backend says it is over already (%i)",
    async (status) => {
      // 401: the row was ended from elsewhere, or expired. 400: the cookie was
      // nobody acting as anybody. Either way keeping it would keep nothing.
      vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(status, "Refused", null));

      const response = await end({ access_token: "stale" });

      expect(response.status).toBe(200);
      expect(cookie(response, "access_token")?.attributes).toContain("Max-Age=0");
    },
  );

  it("passes any other refusal through, cookie kept", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(503, "Unavailable", null));

    const response = await end({ access_token: "imp" });

    expect(response.status).toBe(503);
    expect(cookie(response, "access_token")).toBeUndefined();
  });

  it("answers 500 when the backend could not be reached at all", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await end({ access_token: "imp" });

    expect(response.status).toBe(500);
  });

  it("has nothing to tell the backend for a browser holding no access cookie", async () => {
    const response = await end({ refresh_token: "admin-rt" });

    expect(response.status).toBe(200);
    expect(backendFetch).not.toHaveBeenCalled();
  });
});

describe("signing in without a password", () => {
  it("asks the backend to mail a link, and answers what it said", async () => {
    // Deliberately the same answer whether the address exists or not, which is
    // the backend's decision and this route's job not to leak.
    vi.mocked(backendFetch).mockResolvedValue({ message: "Check your email" });

    const response = await magicLinkRequest(request({}, { email: "kacper@example.com" }));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/magic-link/request", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ email: "kacper@example.com" }),
    });
    await expect(response.json()).resolves.toEqual({ message: "Check your email" });
  });

  it("passes a rate limit through with its own status", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(429, "Too Many Requests", null));

    const response = await magicLinkRequest(request({}, { email: "a@example.com" }));

    expect(response.status).toBe(429);
  });

  it("passes a refusal that is not a rate limit through with its status", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(400, "Bad Request", null));

    const response = await magicLinkRequest(request({}, { email: "a@example.com" }));

    expect(response.status).toBe(400);
  });

  it("answers 500 when the mail request could not be made", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await magicLinkRequest(request({}, { email: "a@example.com" }));

    expect(response.status).toBe(500);
  });

  it("turns a verified link into a session, cookies and all", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await magicLinkVerify(request({}, { token: "one-time" }));

    await expect(response.json()).resolves.toMatchObject({
      user: { id: "u-1" },
      access_token: "at",
      // Null rather than absent: the landing reads this to decide where to go,
      // and a link minted without a path says so (#1214).
      return_to: null,
    });
    expect(cookie(response, "access_token")).toMatchObject({ value: "at" });
    expect(cookie(response, "refresh_token")).toMatchObject({ value: "rt" });
  });

  it("passes on the path the link was minted for", async () => {
    // The path travels in the token because a magic link is followed from an
    // email, where the tab-local store the OAuth round trip uses is empty. This
    // route is the only thing between the token and the page that reads it.
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt", return_to: "/agents/a-1" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await magicLinkVerify(request({}, { token: "one-time" }));

    await expect(response.json()).resolves.toMatchObject({ return_to: "/agents/a-1" });
  });

  it("refuses a link that did not verify, without a session", async () => {
    // The status survives; the *sentence* does not. This route reports
    // `error.message`, which is `BackendApiError`'s own generic string, so an
    // expired link reads as "Backend API error: 400 Bad Request" rather than
    // "This link has expired". Thirty-eight generated routes do the same thing -
    // see `docs/plans/frontend-coverage.md`. Asserted as it behaves, not as it
    // should: a test that claimed the better sentence would be a test of nothing.
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(400, "Bad Request", { detail: "This link has expired" }),
    );

    const response = await magicLinkVerify(request({}, { token: "stale" }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      detail: "Backend API error: 400 Bad Request",
    });
    expect(cookie(response, "access_token")).toBeUndefined();
  });

  it("answers 500 when the verification could not be made", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await magicLinkVerify(request({}, { token: "x" }));

    expect(response.status).toBe(500);
  });
});

describe("finishing an OAuth sign-in", () => {
  it("swaps the single-use code for the token pair, and stores it", async () => {
    // The redirect carries a code, not the tokens (#14): a token in a redirect
    // URL reaches the address bar, the access log and the next Referer.
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await oauthCallback(request({}, { code: "one-time" }));

    expect(backendFetch).toHaveBeenNthCalledWith(1, "/api/v1/oauth/exchange", {
      method: "POST",
      body: JSON.stringify({ code: "one-time" }),
    });
    expect(backendFetch).toHaveBeenNthCalledWith(2, "/api/v1/auth/me", {
      headers: { Authorization: "Bearer at" },
    });
    expect(cookie(response, "access_token")).toMatchObject({ value: "at" });
    expect(cookie(response, "refresh_token")).toMatchObject({ value: "rt" });
  });

  it("refuses a callback carrying no code", async () => {
    const response = await oauthCallback(request({}, {}));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({ code: "MISSING_AUTHORIZATION_CODE" });
    expect(cookie(response, "access_token")).toBeUndefined();
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("passes the backend's refusal of the code through", async () => {
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(401, "Unauthorized", { detail: "Invalid or expired exchange code" }),
    );

    const response = await oauthCallback(request({}, { code: "stale" }));

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ detail: "Invalid or expired exchange code" });
  });

  it("says sign-in failed when the refusal named no reason", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(401, "Unauthorized", null));

    const response = await oauthCallback(request({}, { code: "stale" }));

    await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
  });

  it("answers 500 when the exchange could not be made", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await oauthCallback(request({}, { code: "x" }));

    expect(response.status).toBe(500);
  });
});

describe("registering, and resetting a password", () => {
  it("creates the account and answers 201", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-2", email: "new@example.com" });

    const response = await register(request({}, { email: "new@example.com", password: "secret" }));

    expect(response.status).toBe(201);
    // No cookies: registration may need a verification step, so it does not sign
    // anybody in.
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("puts the backend's reason on a refused registration", async () => {
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(409, "Conflict", { detail: "That email is already registered" }),
    );

    const response = await register(request({}, { email: "taken@example.com", password: "x" }));

    expect(response.status).toBe(409);
    await expect(response.json()).resolves.toEqual({
      detail: "That email is already registered",
    });
  });

  it("forwards a refusal in the API's own envelope", async () => {
    // Every refusal that matters here is an `AppException`, which answers
    // `{"error": {...}}` and carries no `detail` - so reading `detail` and falling
    // back to a generic code turned "this deployment is invite-only" into
    // "registration failed", which says nothing about a rule somebody could satisfy.
    vi.mocked(backendFetch).mockRejectedValue(
      new BackendApiError(403, "Forbidden", {
        error: {
          code: "AUTHORIZATION_ERROR",
          message: "This deployment is invite-only. Ask an administrator to invite you.",
          details: null,
        },
      }),
    );

    const response = await register(request({}, { email: "a@example.com", password: "x" }));

    expect(response.status).toBe(403);
    await expect(response.json()).resolves.toMatchObject({
      error: { message: expect.stringContaining("invite-only") },
    });
  });

  it("forwards the invitation token the form was reached with", async () => {
    // The body goes through whole, which is how the token reaches the sign-up policy
    // without this route knowing what it is for.
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-3", email: "invited@acme.com" });

    await register(
      request({}, { email: "invited@acme.com", password: "secret", invitation_token: "tok" }),
    );

    const [, options] = vi.mocked(backendFetch).mock.calls.at(-1) ?? [];
    expect(JSON.parse(String(options?.body))).toMatchObject({ invitation_token: "tok" });
  });

  it("says registration failed when the refusal named no reason", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(400, "Bad Request", null));

    const response = await register(request({}, { email: "a@example.com", password: "x" }));

    await expect(response.json()).resolves.toEqual({ code: "REGISTRATION_FAILED" });
  });

  it("answers 500 for a registration that could not be attempted", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await register(request({}, { email: "a@example.com", password: "x" }));

    expect(response.status).toBe(500);
  });

  it("forwards a reset request and a reset confirmation", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ message: "Check your email" });
    await passwordResetRequest(request({}, { email: "a@example.com" }));
    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/password-reset/request", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ email: "a@example.com" }),
    });

    vi.mocked(backendFetch).mockResolvedValue({ message: "Password updated" });
    const confirmed = await passwordResetConfirm(
      request({}, { token: "one-time", new_password: "secret" }),
    );
    expect(backendFetch).toHaveBeenCalledWith("/api/v1/auth/password-reset/confirm", {
      method: "POST",
      headers: {},
      body: JSON.stringify({ token: "one-time", new_password: "secret" }),
    });
    await expect(confirmed.json()).resolves.toEqual({ message: "Password updated" });
  });

  it("passes a refused reset through, and a broken one as a 500", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(400, "Bad Request", null));
    expect((await passwordResetRequest(request({}, { email: "a@example.com" }))).status).toBe(400);
    expect((await passwordResetConfirm(request({}, { token: "x" }))).status).toBe(400);

    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));
    expect((await passwordResetRequest(request({}, { email: "a@example.com" }))).status).toBe(500);
    expect((await passwordResetConfirm(request({}, { token: "x" }))).status).toBe(500);
  });
});

/**
 * The rate limit only works if the caller's address survives the BFF and a 429
 * reaches the browser as one (#1047). The backend keys the per-IP bucket on
 * `X-Forwarded-For`, which is the frontend container's unless this hop forwards
 * the client's; and a 429 flattened to "login failed" or a cleared session tells
 * the caller the wrong thing and drops the `Retry-After`.
 */
describe("rate limiting through the BFF", () => {
  function rateLimited() {
    return new BackendApiError(
      429,
      "Too Many Requests",
      {
        error: {
          code: "RATE_LIMIT_EXCEEDED",
          message: "Too many attempts. Try again in a minute.",
          details: { retry_after_seconds: 60 },
        },
      },
      new Headers({ "Retry-After": "60" }),
    );
  }

  it("forwards the caller's address so the limit keys on the client, not the container", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    await login(
      request({}, { email: "a@example.com", password: "s" }, { "x-forwarded-for": "203.0.113.7" }),
    );

    expect(backendFetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/login",
      expect.objectContaining({
        headers: expect.objectContaining({ "x-forwarded-for": "203.0.113.7" }),
      }),
    );
  });

  it("reaches the browser as a rate-limit result with its Retry-After, not a login failure", async () => {
    vi.mocked(backendFetch).mockRejectedValue(rateLimited());

    const response = await login(request({}, { email: "a@example.com", password: "x" }));

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("60");
    await expect(response.json()).resolves.toMatchObject({
      error: { code: "RATE_LIMIT_EXCEEDED" },
    });
  });

  it("does not end the session when the refresh bucket is exhausted", async () => {
    vi.mocked(backendFetch).mockRejectedValue(rateLimited());

    const response = await refresh(request({ refresh_token: "rt" }));

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("60");
    // A wait, not an expired session: the cookies are left untouched rather than
    // cleared, so the caller stays signed in and can retry.
    expect(cookie(response, "access_token")).toBeUndefined();
    expect(cookie(response, "refresh_token")).toBeUndefined();
  });

  it.each([
    ["register", register],
    ["magic-link/verify", magicLinkVerify],
    ["password-reset/request", passwordResetRequest],
    ["password-reset/confirm", passwordResetConfirm],
  ])("carries the rate limit and its Retry-After through %s too", async (_name, route) => {
    vi.mocked(backendFetch).mockRejectedValue(rateLimited());

    const response = await route(
      request({}, { email: "a@example.com", token: "t", new_password: "p", password: "p" }),
    );

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("60");
  });
});
