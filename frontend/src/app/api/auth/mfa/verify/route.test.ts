/** @vitest-environment node */
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackendApiError, backendFetch } from "@/lib/server-api";

import { POST } from "./route";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request() {
  return new NextRequest("http://localhost:3000/api/auth/mfa/verify", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.9" },
    body: JSON.stringify({ mfa_token: "challenge", code: "123456" }),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("POST /api/auth/mfa/verify", () => {
  it("preserves an invalid-code refusal without creating a session", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(401, "Unauthorized", { detail: "The code is invalid or expired" }),
    );

    const response = await POST(request());

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ detail: "The code is invalid or expired" });
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backendFetch).toHaveBeenCalledTimes(1);
  });

  it.each([null, {}, { detail: "" }])(
    "keeps an unexplained refusal closed when its body is %j",
    async (data) => {
      vi.mocked(backendFetch).mockRejectedValueOnce(new BackendApiError(403, "Forbidden", data));

      const response = await POST(request());

      expect(response.status).toBe(403);
      await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
      expect(response.headers.getSetCookie()).toEqual([]);
      expect(backendFetch).toHaveBeenCalledTimes(1);
    },
  );

  it("preserves rate limiting and its retry delay without creating a session", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(
        429,
        "Too Many Requests",
        { error: { code: "RATE_LIMIT_EXCEEDED" } },
        new Headers({ "retry-after": "30" }),
      ),
    );

    const response = await POST(request());

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backendFetch).toHaveBeenCalledTimes(1);
  });

  it("reports a failed verification transport without creating a session", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const response = await POST(request());

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({ code: "INTERNAL_SERVER_ERROR" });
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backendFetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["no response headers", undefined],
    ["no location header", new Headers()],
    ["a malformed location", new Headers({ location: "not an absolute URL" })],
    [
      "the wrong host",
      new Headers({ location: "agenticos://other/callback?code=one&desktop_nonce=n" }),
    ],
    [
      "the wrong path",
      new Headers({ location: "agenticos://auth/other?code=one&desktop_nonce=n" }),
    ],
    [
      "an empty exchange code",
      new Headers({ location: "agenticos://auth/callback?code=&desktop_nonce=n" }),
    ],
    ["no desktop nonce", new Headers({ location: "agenticos://auth/callback?code=one" })],
  ] as const)("refuses a desktop redirect with %s", async (_description, headers) => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(307, "Temporary Redirect", null, headers),
    );

    const response = await POST(request());

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backendFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the browser JSON session response and cookies", async () => {
    vi.mocked(backendFetch)
      .mockResolvedValueOnce({ access_token: "at", refresh_token: "rt" })
      .mockResolvedValueOnce({ id: "u-1" });

    const response = await POST(request());

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      user: { id: "u-1" },
      access_token: "at",
      return_to: null,
    });
    expect(response.headers.getSetCookie()).toHaveLength(2);
    expect(backendFetch).toHaveBeenNthCalledWith(
      1,
      "/api/v1/auth/mfa/verify",
      expect.objectContaining({ method: "POST", redirect: "manual" }),
    );
  });

  it("returns the backend desktop callback for the client to open", async () => {
    const location = "agenticos://auth/callback?code=single-use&desktop_nonce=nonce";
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(307, "Temporary Redirect", null, new Headers({ location })),
    );

    const response = await POST(request());

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ desktop_callback_url: location });
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(backendFetch).toHaveBeenCalledTimes(1);
  });

  it("does not pass through a non-AgenticOS redirect", async () => {
    vi.mocked(backendFetch).mockRejectedValueOnce(
      new BackendApiError(
        307,
        "Temporary Redirect",
        null,
        new Headers({ location: "https://example.com/callback?code=secret" }),
      ),
    );

    const response = await POST(request());

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({ code: "LOGIN_FAILED" });
  });
});
