import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BackendApiError, backendFetch, bffJson, bffRefusal, getAuthHeaders } from "./server-api";

/**
 * The server-side half of every proxy route.
 *
 * This is the only place the backend's URL exists, which is the reason the
 * browser talks to `/api/*` at all. Two rules it has to keep: a multipart body
 * is forwarded without a `Content-Type`, because the boundary belongs to the
 * body it came with, and a refused response becomes an error carrying the
 * status - a route that swallowed it would answer 200 with nothing in it.
 */
let fetchMock: ReturnType<typeof vi.fn>;

function respond(response: Partial<Response>) {
  fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: "OK",
    text: () => Promise.resolve("{}"),
    json: () => Promise.resolve({}),
    ...response,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => respond({}));
afterEach(() => vi.unstubAllGlobals());

describe("backendFetch", () => {
  it("addresses the backend, which no browser request ever names", async () => {
    await backendFetch("/api/v1/agents");

    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/v1/agents");
  });

  it("appends query parameters", async () => {
    await backendFetch("/api/v1/runs", { params: { agent_id: "a1" } });

    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/v1/runs?agent_id=a1");
  });

  it("sends JSON by default and forwards the caller's own headers", async () => {
    await backendFetch("/api/v1/agents", {
      method: "POST",
      body: JSON.stringify({ name: "Support" }),
      headers: { Authorization: "Bearer t" },
    });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      Authorization: "Bearer t",
    });
  });

  it("forwards a multipart body without a content type of its own", async () => {
    // The boundary is in the body it was handed; naming the type here drops it and
    // FastAPI refuses a body it was just given.
    const form = new FormData();
    form.append("file", new File(["x"], "a.pdf"));

    await backendFetch("/api/v1/rag/ingest", { method: "POST", body: form });

    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.headers).not.toHaveProperty("Content-Type");
  });

  it("reads an empty body as null rather than failing to parse it", async () => {
    respond({ status: 204, text: () => Promise.resolve("") });

    await expect(backendFetch("/api/v1/agents/a1")).resolves.toBeNull();
  });

  it("hands back the raw text when asked, for what is not JSON", async () => {
    // A download proxy forwards bytes; parsing them would corrupt the response.
    respond({ text: () => Promise.resolve("id,name\n1,Support") });

    await expect(backendFetch("/api/v1/export", { raw: true })).resolves.toBe("id,name\n1,Support");
  });

  it("raises the backend's status, so the route can answer with the same one", async () => {
    respond({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: () => Promise.resolve({ detail: "Missing required permission" }),
    });

    const failure = await backendFetch("/api/v1/agents").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(BackendApiError);
    expect(failure).toMatchObject({
      status: 403,
      statusText: "Forbidden",
      data: { detail: "Missing required permission" },
    });
  });

  it("still raises when the refusal has no readable body", async () => {
    respond({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: () => Promise.reject(new Error("not json")),
    });

    const failure = await backendFetch("/api/v1/agents").catch((error: unknown) => error);

    expect(failure).toMatchObject({ status: 502, data: null });
  });
});

describe("bffJson", () => {
  it("stamps no-store, so a list refetched right after a write reaches the server", () => {
    // Every answer here depends on the caller's cookie, permissions and org
    // header. Left unmarked, the members / invitations / integrations lists
    // refetched after a create or revoke could be served stale (#553, same
    // class as #230).
    expect(bffJson({ items: [] }).headers.get("Cache-Control")).toBe("no-store");
  });

  it("keeps the status the caller asked for", () => {
    expect(bffJson({ id: "x" }, { status: 201 }).status).toBe(201);
  });

  it("leaves an explicit cache policy alone rather than overwriting it", () => {
    // A response that deliberately caches - an icon, an embed bundle - says so,
    // and no-store must not clobber it.
    const response = bffJson("body", { headers: { "Cache-Control": "public, max-age=300" } });
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=300");
  });
});

describe("bffRefusal", () => {
  it("carries the status and no-store, so a refusal is never cached either", () => {
    const response = bffRefusal("NOT_AUTHENTICATED", 401);
    expect(response.status).toBe(401);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
});

describe("getAuthHeaders", () => {
  it("forwards the caller's own authorization, unchanged", () => {
    expect(getAuthHeaders("Bearer abc")).toEqual({ Authorization: "Bearer abc" });
  });

  it("sends nothing rather than an empty header for an unauthenticated request", () => {
    // Which is a public route; an `Authorization: ` header would be rejected
    // outright instead of falling through to the anonymous path.
    expect(getAuthHeaders(null)).toEqual({});
  });
});
