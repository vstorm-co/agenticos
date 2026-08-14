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

import { GET as conversationDetail } from "./conversations/[id]/route";
import { GET as conversations } from "./conversations/route";
import { GET as organizations } from "./organizations/route";
import { GET as ratingsSummary } from "./ratings/summary/route";
import { GET as stats } from "./stats/route";
import { GET as system } from "./system/route";
import { GET as getUser, PATCH as patchUser, DELETE as deleteUser } from "./users/[userId]/route";
import { POST as impersonate } from "./users/[userId]/impersonate/route";
import { GET as users } from "./users/route";
import { requireAdmin } from "@/lib/admin-auth";
import { BackendApiError, backendFetch } from "@/lib/server-api";

vi.mock("@/lib/admin-auth", () => ({ requireAdmin: vi.fn() }));
vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

function request(url = "http://localhost:3000/api/admin/users", body?: unknown): NextRequest {
  return new NextRequest(url, {
    ...(body === undefined ? {} : { method: "PATCH", body: JSON.stringify(body) }),
  });
}

/** The path the route forwarded to. */
function forwarded(nth = 0): string {
  return vi.mocked(backendFetch).mock.calls[nth]![0] as string;
}

/**
 * Every route on this list, with a call that should reach the backend.
 *
 * The gate is what is being asserted, not the payload: each of these is behind
 * `is_app_admin`, and a route that forgot to ask would expose the whole
 * deployment's users, conversations and ratings to any signed-in member.
 */
const GUARDED: [string, () => Promise<Response>][] = [
  ["conversations", () => conversations(request())],
  [
    "one conversation",
    () => conversationDetail(request(), { params: Promise.resolve({ id: "c-1" }) }),
  ],
  ["organizations", () => organizations(request())],
  ["a ratings summary", () => ratingsSummary(request())],
  ["stats", () => stats(request())],
  ["system", () => system(request())],
  ["users", () => users(request())],
  [
    "reading one user",
    () =>
      getUser(request("http://localhost:3000/api/admin/users/u-1"), {
        params: Promise.resolve({ userId: "u-1" }),
      }),
  ],
  [
    "a user edit",
    () =>
      patchUser(request("http://localhost:3000/api/admin/users/u-1", { is_active: false }), {
        params: Promise.resolve({ userId: "u-1" }),
      }),
  ],
  [
    "a user deletion",
    () =>
      deleteUser(request("http://localhost:3000/api/admin/users/u-1"), {
        params: Promise.resolve({ userId: "u-1" }),
      }),
  ],
  [
    "an impersonation",
    () =>
      impersonate(request("http://localhost:3000/api/admin/users/u-1/impersonate"), {
        params: Promise.resolve({ userId: "u-1" }),
      }),
  ],
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(requireAdmin).mockResolvedValue({ accessToken: "at" });
  vi.mocked(backendFetch).mockResolvedValue({ items: [], total: 0 });
});

/**
 * The deployment-admin routes.
 *
 * There is one rule here and it is the only one that matters: every route asks
 * `requireAdmin` first, and answers with whatever that refuses with. The check
 * is a round trip to the backend's own `/auth/me` rather than anything read off
 * the request, because the cookie is the only thing the browser controls.
 *
 * The rest is forwarding. What is worth pinning about the forwarding is the
 * query string: these screens are paged and filtered, and a dropped parameter
 * shows the whole table under a heading that says it is filtered.
 */
describe("the admin gate", () => {
  it.each(GUARDED)("guards %s", async (_name, call) => {
    const refusal = new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 });
    vi.mocked(requireAdmin).mockResolvedValue({
      error: refusal as unknown as Awaited<ReturnType<typeof requireAdmin>> extends {
        error: infer E;
      }
        ? E
        : never,
    } as Awaited<ReturnType<typeof requireAdmin>>);

    const response = await call();

    expect(response.status).toBe(403);
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it.each(GUARDED)("forwards %s with the admin's own token", async (_name, call) => {
    await call();

    expect(backendFetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: "Bearer at" }),
    });
  });

  it.each(GUARDED)("answers 500 when %s could not be forwarded", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await call();

    expect(response.status).toBe(500);
  });

  it.each(GUARDED)("passes the backend's own refusal of %s through", async (_name, call) => {
    vi.mocked(backendFetch).mockRejectedValue(new BackendApiError(409, "Conflict", null));

    const response = await call();

    expect(response.status).toBe(409);
  });
});

describe("what the admin screens filter on", () => {
  it("carries every conversation filter, and drops the ones nobody set", async () => {
    await conversations(
      request(
        "http://localhost:3000/api/admin/conversations?skip=20&limit=10&search=refund&user_id=u-1&agent_id=a-1&status=archived&sort_by=updated_at&sort_dir=asc",
      ),
    );

    const path = forwarded();
    for (const expected of [
      "skip=20",
      "limit=10",
      "search=refund",
      "user_id=u-1",
      "agent_id=a-1",
      "status=archived",
      "sort_by=updated_at",
      "sort_dir=asc",
    ]) {
      expect(path).toContain(expected);
    }
  });

  it("forwards nothing at all when nothing was filtered", async () => {
    await conversations(request("http://localhost:3000/api/admin/conversations"));

    expect(forwarded()).toBe("/api/v1/admin/conversations");
  });

  it("addresses one conversation by id", async () => {
    await conversationDetail(request(), { params: Promise.resolve({ id: "c-9" }) });

    expect(forwarded()).toBe("/api/v1/admin/conversations/c-9");
  });

  it("carries every user-list filter, sort included", async () => {
    // The sort keys used to be dropped here while the screen went on sending
    // them, so clicking a column header flipped the arrow and reordered
    // nothing: the backend fell back to `created_at desc` every time.
    await users(
      request(
        "http://localhost:3000/api/admin/users?skip=50&limit=25&search=a&sort_by=email&sort_dir=asc",
      ),
    );

    const path = forwarded();
    for (const expected of ["skip=50", "limit=25", "search=a", "sort_by=email", "sort_dir=asc"]) {
      expect(path).toContain(expected);
    }
  });

  it("forwards nothing at all when the user list was not filtered", async () => {
    await users(request("http://localhost:3000/api/admin/users"));

    expect(forwarded()).toBe("/api/v1/admin/users");
  });

  it("leaves the summary window to the backend when none was asked for", async () => {
    await ratingsSummary(request("http://localhost:3000/api/admin/ratings/summary"));
    expect(forwarded()).toBe("/api/v1/admin/ratings/summary");
  });

  it("forwards the dashboard's window to the summary", async () => {
    // The proxy read only `days` and always sent one, so the dashboard's
    // period reached the backend as a trailing thirty days whatever was
    // picked - a card that could not answer a question about last month.
    await ratingsSummary(
      request("http://localhost:3000/api/admin/ratings/summary?from=2026-07-01&to=2026-07-31"),
    );
    expect(forwarded()).toBe("/api/v1/admin/ratings/summary?from=2026-07-01&to=2026-07-31");
  });

  it("passes the organization search through as it stands", async () => {
    await organizations(request("http://localhost:3000/api/admin/organizations?search=acme"));

    expect(forwarded()).toBe("/api/v1/admin/organizations?search=acme");
  });
});

describe("acting on one user", () => {
  it("reads that user by id", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-1", email: "kacper@example.com" });

    const response = await getUser(request("http://localhost:3000/api/admin/users/u-1"), {
      params: Promise.resolve({ userId: "u-1" }),
    });

    expect(forwarded()).toBe("/api/v1/admin/users/u-1");
    await expect(response.json()).resolves.toMatchObject({ id: "u-1" });
  });

  it("sends the edit to that user's endpoint", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ id: "u-1", is_active: false });

    const response = await patchUser(
      request("http://localhost:3000/api/admin/users/u-1", { is_active: false }),
      { params: Promise.resolve({ userId: "u-1" }) },
    );

    expect(forwarded()).toBe("/api/v1/admin/users/u-1");
    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ is_active: false }),
    });
    expect(response.status).toBe(200);
  });

  it("deletes that user and answers with no content", async () => {
    vi.mocked(backendFetch).mockResolvedValue(null);

    const response = await deleteUser(request("http://localhost:3000/api/admin/users/u-1"), {
      params: Promise.resolve({ userId: "u-1" }),
    });

    expect(vi.mocked(backendFetch).mock.calls[0]![1]).toMatchObject({ method: "DELETE" });
    expect(response.status).toBe(204);
  });

  it("mints an impersonation token on that user's own endpoint", async () => {
    // The most privileged action in the product: it hands back a token that acts
    // as somebody else.
    vi.mocked(backendFetch).mockResolvedValue({ access_token: "imp" });

    const response = await impersonate(
      request("http://localhost:3000/api/admin/users/u-1/impersonate"),
      { params: Promise.resolve({ userId: "u-1" }) },
    );

    expect(forwarded()).toBe("/api/v1/admin/users/u-1/impersonate");
    await expect(response.json()).resolves.toMatchObject({ access_token: "imp" });
  });
});
