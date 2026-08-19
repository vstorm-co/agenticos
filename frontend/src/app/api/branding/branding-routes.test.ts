/**
 * @vitest-environment node
 *
 * Server routes. The suite's default is jsdom, and running a route handler in a
 * browser-shaped global is a lie about where it executes.
 */
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET as readBranding } from "./route";
import { GET as readMark } from "./mark/[kind]/route";
import { GET as readNotice } from "./notice/route";
import { backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

const fetchBackend = vi.mocked(backendFetch);

function request(url: string, { signedIn = false }: { signedIn?: boolean } = {}): NextRequest {
  return new NextRequest(url, { headers: signedIn ? { cookie: "access_token=at" } : {} });
}

afterEach(() => {
  // `clearAllMocks` as well as `restoreAllMocks`: the module mock's `vi.fn()` is
  // not a spy, so restoring leaves its call history from the previous test and a
  // "was never called" assertion passes or fails on the wrong run.
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the public identity route", () => {
  it("answers without a session", async () => {
    // Structural, not a convenience: the sign-in page, the register form and the
    // maintenance screen all read it before a session exists.
    fetchBackend.mockResolvedValue({ app_name: "Acme AI" });

    const response = await readBranding(request("http://x/api/branding"));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ app_name: "Acme AI" });
  });

  it("is never cached", async () => {
    // A renamed deployment still answering its old name looks like a save that
    // did not take.
    fetchBackend.mockResolvedValue({});

    const response = await readBranding(request("http://x/api/branding"));

    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchBackend).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("passes the backend's own status and message through", async () => {
    const { BackendApiError } =
      await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
    fetchBackend.mockRejectedValue(new BackendApiError(503, "Service Unavailable"));

    const response = await readBranding(request("http://x/api/branding"));

    expect(response.status).toBe(503);
  });

  it("answers a refusal when the backend cannot be reached", async () => {
    fetchBackend.mockRejectedValue(new Error("ECONNREFUSED"));

    expect((await readBranding(request("http://x/api/branding"))).status).toBe(500);
  });
});

describe("the announcement route", () => {
  it("refuses a caller with no session", async () => {
    // An announcement is an operator talking to the people using the deployment.
    // A stranger on the sign-in page has no part in it.
    const response = await readNotice(request("http://x/api/branding/notice"));

    expect(response.status).toBe(401);
    expect(fetchBackend).not.toHaveBeenCalled();
  });

  it("turns the cookie into the bearer token the backend gate reads", async () => {
    fetchBackend.mockResolvedValue({ message: "Window at 22:00", level: "warning" });

    const response = await readNotice(request("http://x/api/branding/notice", { signedIn: true }));

    expect(response.status).toBe(200);
    expect(fetchBackend).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ headers: { Authorization: "Bearer at" } }),
    );
  });

  it("passes a backend refusal through with its status", async () => {
    const { BackendApiError } =
      await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
    fetchBackend.mockRejectedValue(new BackendApiError(403, "Forbidden"));

    const response = await readNotice(request("http://x/api/branding/notice", { signedIn: true }));

    expect(response.status).toBe(403);
  });

  it("answers a refusal when the backend cannot be reached", async () => {
    fetchBackend.mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await readNotice(request("http://x/api/branding/notice", { signedIn: true }));

    expect(response.status).toBe(500);
  });
});

describe("the mark route", () => {
  function backendServes(body: BodyInit | null, headers: Record<string, string> = {}) {
    // A fresh `Response` per call: a body can only be read once, so a single
    // resolved instance makes the second request fail on a consumed stream.
    // The parameters are declared so the call assertions below can read the URL:
    // an arg-less `vi.fn` infers an empty tuple, and `calls[0][0]` then has no type.
    const mock = vi.fn(async (_url: string, _init?: RequestInit) => {
      void _init;
      return new Response(body, { status: 200, headers });
    });
    vi.stubGlobal("fetch", mock);
    return mock;
  }

  it("serves either mark without a session", async () => {
    // A browser fetching a favicon sends no cookie this app would read.
    backendServes("png", { "content-type": "image/png" });

    for (const kind of ["logo", "favicon"]) {
      const response = await readMark(request(`http://x/api/branding/mark/${kind}?v=1`), {
        params: Promise.resolve({ kind }),
      });
      expect(response.status).toBe(200);
    }
  });

  it("refuses a kind the whitelist does not name", async () => {
    // The segment reaches an API path, and the two images this deployment has are
    // the two it has.
    const mock = backendServes("png");

    const response = await readMark(request("http://x/api/branding/mark/../../secrets"), {
      params: Promise.resolve({ kind: "../../secrets" }),
    });

    expect(response.status).toBe(404);
    expect(mock).not.toHaveBeenCalled();
  });

  it("forwards the version token it was given", async () => {
    const mock = backendServes("png", { "content-type": "image/png" });

    await readMark(request("http://x/api/branding/mark/logo?v=42"), {
      params: Promise.resolve({ kind: "logo" }),
    });

    expect(mock.mock.calls[0]?.[0]).toContain("?v=42");
  });
});
