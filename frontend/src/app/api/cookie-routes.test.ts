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

import { GET as health } from "./health/route";
import { POST as acceptInvitation, DELETE as declineInvitation } from "./invitations/[token]/route";
import { GET as listIntegrations, POST as createIntegration } from "./orgs/[id]/integrations/route";
import { GET as connectors } from "./orgs/[id]/integrations/connectors/route";
import { DELETE as deleteIntegration } from "./orgs/[id]/integrations/[sourceId]/route";
import { POST as triggerIntegration } from "./orgs/[id]/integrations/[sourceId]/trigger/route";
import { GET as getMe, PATCH as patchMe } from "./users/me/route";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

/** A signed-in request, unless `signedIn` says otherwise. */
function request(
  url = "http://localhost:3000/api/orgs/org-1/integrations",
  { body, signedIn = true }: { body?: unknown; signedIn?: boolean } = {},
): NextRequest {
  return new NextRequest(url, {
    headers: signedIn ? { cookie: "access_token=at" } : {},
    ...(body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }),
  });
}

const org = { params: Promise.resolve({ id: "org-1" }) };

/**
 * Every hand-rolled route that reads the session cookie itself, with a call
 * that should reach the backend.
 *
 * The plain forwarders these used to sit beside now go through `platformProxy`;
 * what is left is genuinely special - an org integration whose tenant travels
 * in a header rather than the path, an invitation addressed by its token, the
 * caller's own profile. Two invariants remain, and both fail silently. A route
 * that forgot to check the cookie forwards an unauthenticated request and lets
 * the backend decide, which turns a 401 into whatever that endpoint does with no
 * token. And a route that forgot to forward the token asks the backend as
 * nobody, which for a listing endpoint answers an empty list rather than an
 * error - a page that says "nothing here" about data that plainly exists.
 */
const COOKIE_GATED: [string, (signedIn: boolean) => Promise<Response>][] = [
  [
    "the integration list",
    (s) =>
      listIntegrations(
        request("http://localhost:3000/api/orgs/org-1/integrations", { signedIn: s }),
        org,
      ),
  ],
  [
    "creating an integration",
    (s) =>
      createIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations", {
          body: { name: "Drive" },
          signedIn: s,
        }),
        org,
      ),
  ],
  [
    "the connector list",
    (s) =>
      connectors(
        request("http://localhost:3000/api/orgs/org-1/integrations/connectors", { signedIn: s }),
        org,
      ),
  ],
  [
    "removing an integration",
    (s) =>
      deleteIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations/s-1", { signedIn: s }),
        { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
      ),
  ],
  [
    "triggering a sync",
    (s) =>
      triggerIntegration(
        request("http://localhost:3000/api/orgs/org-1/integrations/s-1/trigger", { signedIn: s }),
        { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
      ),
  ],
  [
    "accepting an invitation",
    (s) =>
      acceptInvitation(request("http://localhost:3000/api/invitations/tok", { signedIn: s }), {
        params: Promise.resolve({ token: "tok" }),
      }),
  ],
  [
    "declining an invitation",
    (s) =>
      declineInvitation(request("http://localhost:3000/api/invitations/tok", { signedIn: s }), {
        params: Promise.resolve({ token: "tok" }),
      }),
  ],
  [
    "the caller's own profile",
    (s) => getMe(request("http://localhost:3000/api/users/me", { signedIn: s })),
  ],
  [
    "editing the caller's profile",
    (s) =>
      patchMe(
        request("http://localhost:3000/api/users/me", { body: { full_name: "K" }, signedIn: s }),
      ),
  ],
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(backendFetch).mockResolvedValue({ items: [], total: 0 });
});

describe("the routes that read the session cookie", () => {
  it.each(COOKIE_GATED)("refuses %s without a session", async (_name, call) => {
    const response = await call(false);

    expect(response.status).toBe(401);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it.each(COOKIE_GATED)("forwards %s with the caller's own token", async (_name, call) => {
    // Not forwarding it is the quiet failure: the backend answers as nobody,
    // which for a listing is an empty list rather than an error.
    await call(true);

    expect(backendFetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: "Bearer at" }),
    });
  });

  it.each(COOKIE_GATED)("passes the backend's refusal of %s through", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(403, "Forbidden", null));

    const response = await call(true);

    expect(response.status).toBe(403);
  });

  it.each(COOKIE_GATED)("answers 500 when %s could not be forwarded", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await call(true);

    expect(response.status).toBe(500);
  });

  it.each(COOKIE_GATED)("addresses %s under the platform's v1 prefix", async (_name, call) => {
    // The one thing a copied route file gets wrong: forwarding to a path that
    // does not exist, which answers 404 and renders as an empty page.
    await call(true);

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toMatch(/^\/api\/v1\//);
  });
});

describe("the paths each one addresses", () => {
  it("addresses an org integration by source, naming the organization in a header", async () => {
    // These live under `/org/integrations` on the backend rather than nested
    // under an organization id, so the tenant travels in `X-Organization-Id` -
    // and a route that dropped the header would act on the caller's personal
    // organization instead.
    await triggerIntegration(
      request("http://localhost:3000/api/orgs/org-1/integrations/s-1/trigger"),
      { params: Promise.resolve({ id: "org-1", sourceId: "s-1" }) },
    );

    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/org/integrations/s-1/trigger");
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      headers: expect.objectContaining({ "X-Organization-Id": "org-1" }),
    });
  });

  it("accepts an invitation on the accept endpoint, and declines on the invitation itself", async () => {
    // Two different backend routes, and posting to the wrong one is how an
    // accept screen once announced success to somebody who had joined nothing.
    await acceptInvitation(request("http://localhost:3000/api/invitations/tok"), {
      params: Promise.resolve({ token: "tok" }),
    });
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/invitations/tok/accept");

    vi.mocked(backendFetch).mockClear();
    await declineInvitation(request("http://localhost:3000/api/invitations/tok"), {
      params: Promise.resolve({ token: "tok" }),
    });
    expect(vi.mocked(backendFetch).mock.calls[0]![0]).toBe("/api/v1/invitations/tok");
  });
});

describe("the health check", () => {
  it("answers what the backend said", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ status: "ok" });

    const response = await health();

    await expect(response.json()).resolves.toEqual({ status: "ok" });
  });

  it("says the backend is unavailable, with its own status", async () => {
    // A health check needs no session: it is what a load balancer asks.
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(503, "Unavailable", null));

    const response = await health();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ code: "BACKEND_UNAVAILABLE" });
  });

  it("answers 500 when the backend could not be reached at all", async () => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await health();

    expect(response.status).toBe(500);
  });
});
