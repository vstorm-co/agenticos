/**
 * Tests for the BFF proxy, and two sweeps over everything that talks to it.
 *
 * The sweeps exist because both failures they catch shipped, and neither broke
 * a single test. The whole platform surface - agents, skills, runs, approvals,
 * providers, permissions - once called `/api/*` paths with no route file behind
 * them: every request a Next 404. Then `/kb` and `/rag` shipped hand-rolled
 * route files that forwarded the token and forgot the active organization, so
 * both pages answered for the caller's personal organization and rendered an
 * empty list. Nothing noticed either: the unit tests mock `apiClient`, and an
 * E2E spec asserting on a heading and a button passes against a page whose every
 * query failed.
 *
 * So one sweep asks whether every path the client calls has a route behind it,
 * and the other asks whether every route that forwards to an org-scoped backend
 * path carries the organization. Fixing the two files without the second one
 * would only mean the next hand-rolled route repeats the omission.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { sourceFiles } from "@/test-utils/source-files";

import { platformProxy } from "./platform-proxy";

const BACKEND = "http://localhost:8000";

function request(url: string, init: RequestInit & { token?: string } = {}) {
  const { token = "tok", ...rest } = init;
  const req = new NextRequest(new Request(`http://localhost:3000${url}`, rest));
  if (token) req.cookies.set("access_token", token);
  return req;
}

/** What the proxy passed to `fetch`, as one call. */
type ForwardedCall = { url: string; init: RequestInit & { headers: Record<string, string> } };

function backendReplies(body: string, init: ResponseInit = {}) {
  // `null`, not `""` - the Response constructor rejects a body on a 204.
  const fetchMock = vi.fn().mockResolvedValue(new Response(body || null, init));
  vi.stubGlobal("fetch", fetchMock);
  return {
    /** The single forwarded call, or a failure if nothing was forwarded. */
    forwarded(): ForwardedCall {
      const [url, init] = fetchMock.mock.calls[0] ?? [];
      if (typeof url !== "string" || !init) throw new Error("nothing was forwarded");
      return { url, init } as ForwardedCall;
    },
    calls: () => fetchMock.mock.calls.length,
  };
}

describe("platformProxy", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards the path and query verbatim to the backend's v1 prefix", async () => {
    const backend = backendReplies('{"items":[]}');

    await platformProxy().GET(request("/api/agents/abc/versions?limit=5"));

    expect(backend.forwarded().url).toBe(`${BACKEND}/api/v1/agents/abc/versions?limit=5`);
  });

  it("sends the access token from the cookie, never from the client", async () => {
    const backend = backendReplies("{}");

    await platformProxy().GET(request("/api/agents", { token: "secret-token" }));

    expect(backend.forwarded().init.headers.Authorization).toBe("Bearer secret-token");
  });

  it("refuses without a session instead of asking the backend", async () => {
    const backend = backendReplies("{}");

    const response = await platformProxy().GET(request("/api/agents", { token: "" }));

    expect(response.status).toBe(401);
    expect(backend.calls()).toBe(0);
  });

  it("forwards the active organization", async () => {
    // Without this header every org-scoped request answers for the user's
    // personal organization instead of the one the UI is showing.
    const backend = backendReplies("{}");

    await platformProxy().GET(
      request("/api/agents", { headers: { "X-Organization-Id": "org-1" } }),
    );

    expect(backend.forwarded().init.headers["X-Organization-Id"]).toBe("org-1");
  });

  it("keeps the backend's status and body on a refusal", async () => {
    // A 403 that arrives as a generic error is the difference between "you
    // cannot do this" and "something broke".
    backendReplies('{"detail":"You cannot edit this agent"}', { status: 403 });

    const response = await platformProxy().DELETE(request("/api/agents/abc", { method: "DELETE" }));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "You cannot edit this agent" });
  });

  it("passes a body through on writes", async () => {
    const backend = backendReplies("{}");

    await platformProxy().POST(
      request("/api/agents", { method: "POST", body: JSON.stringify({ spec: { name: "S" } }) }),
    );

    // Bytes, so an upload survives the hop; decoded here only to read it.
    const body = backend.forwarded().init.body as ArrayBuffer;
    expect(new TextDecoder().decode(body)).toBe('{"spec":{"name":"S"}}');
  });

  it("does not read a body on a GET", async () => {
    const backend = backendReplies("{}");

    await platformProxy().GET(request("/api/agents"));

    expect(backend.forwarded().init.body).toBeUndefined();
  });

  it("forwards the caller's own content type, boundary and all", async () => {
    // A file upload is multipart with a boundary only the browser knows.
    // Overwriting it with `application/json` - which this proxy used to do
    // unconditionally - makes FastAPI report the file field as missing.
    const backend = backendReplies("{}");
    const boundary = "multipart/form-data; boundary=----WebKitFormBoundaryXYZ";

    await platformProxy().POST(
      request("/api/kb/abc/documents", {
        method: "POST",
        headers: { "Content-Type": boundary },
        body: "----WebKitFormBoundaryXYZ",
      }),
    );

    expect(backend.forwarded().init.headers["Content-Type"]).toBe(boundary);
  });

  it("moves a binary body through unchanged in both directions", async () => {
    // A PDF is not UTF-8. Reading the response as text and re-encoding it - the
    // shape every hand-rolled route in this app was written in - replaces every
    // byte it cannot decode, which corrupts the file silently.
    const pdf = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37, 0x00, 0xff, 0xfe]);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(pdf, {
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="handbook.pdf"',
          },
        }),
      ),
    );

    const response = await platformProxy().GET(request("/api/kb/abc/documents/d1/download"));

    expect(new Uint8Array(await response.arrayBuffer())).toEqual(pdf);
    expect(response.headers.get("Content-Type")).toBe("application/pdf");
    expect(response.headers.get("Content-Disposition")).toBe('attachment; filename="handbook.pdf"');
  });

  it("returns an empty 204 rather than inventing a body", async () => {
    backendReplies("", { status: 204 });

    const response = await platformProxy().DELETE(
      request("/api/agents/abc/sharing/grants/u1", { method: "DELETE" }),
    );

    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
  });

  it("refuses to let a list be cached when the backend named no policy", async () => {
    // Silence is not "do not cache". A 200 with no `Cache-Control`, no `ETag` and
    // no `Last-Modified` is one the browser may reuse on its own judgement - so a
    // list refetched right after a write could be answered without the server
    // being asked, and the page kept rendering the row it had just created as
    // absent (#230). Every answer here depends on a cookie, a permission set and
    // an organization header, so there is nothing to cache in the first place.
    backendReplies('{"items":[],"total":0}');

    const response = await platformProxy().GET(request("/api/secrets"));

    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it("still lets the backend choose a policy where it has one", async () => {
    // The catalog icons and the embed bundle are cacheable and say so. A proxy
    // that overrode them would be inventing a policy rather than forwarding one.
    backendReplies("{}", { headers: { "cache-control": "public, max-age=86400, immutable" } });

    const response = await platformProxy().GET(request("/api/catalog/icons/github.svg"));

    expect(response.headers.get("Cache-Control")).toBe("public, max-age=86400, immutable");
  });
});

// -- the sweeps ---------------------------------------------------------------

const SRC = join(process.cwd(), "src");
const APP_ROOT = join(SRC, "app", "api");

/**
 * Backend prefixes whose routes resolve the caller's *active* organization
 * rather than reading one out of the URL.
 *
 * Written down here because a frontend test cannot ask FastAPI which routes
 * depend on `get_active_organization`. Kept short on purpose: it is a list of
 * prefixes, not of endpoints, so a new backend route under one of them is
 * covered the day it lands.
 */
const ORG_SCOPED_BACKEND_PREFIXES = [
  "/api/v1/agents",
  "/api/v1/approvals",
  "/api/v1/audit",
  "/api/v1/channels",
  "/api/v1/conversations",
  "/api/v1/kb",
  "/api/v1/mcp-connections",
  "/api/v1/me/permissions",
  "/api/v1/org/integrations",
  "/api/v1/providers",
  "/api/v1/rag",
  "/api/v1/ratings",
  "/api/v1/roles",
  "/api/v1/runs",
  "/api/v1/secrets",
  "/api/v1/skills",
  "/api/v1/spend",
  "/api/v1/stats",
];

/** Backend paths a route file forwards to, taken from its source. */
function forwardedBackendPaths(source: string): string[] {
  return [...source.matchAll(/["'`](\/api\/v1\/[^"'`\s?]*)/g)].map((match) => match[1] ?? "");
}

describe("every org-scoped request carries the organization", () => {
  // The bug this replaces: `/kb` and `/rag` were served by hand-rolled route
  // files that forwarded the token and not `X-Organization-Id`, so both pages
  // answered for the caller's personal organization no matter what the UI was
  // showing. Fixing the two files would have left the next hand-rolled route to
  // make the same omission, which is why this is a sweep and not a unit test.
  const routeFiles = sourceFiles(APP_ROOT, (name) => name.endsWith("route.ts"));

  it("finds the route files it is supposed to be checking", () => {
    expect(routeFiles.length).toBeGreaterThan(20);
  });

  it("recognises an org-scoped backend path", () => {
    expect(forwardedBackendPaths('await backendFetch("/api/v1/kb/x")')).toEqual(["/api/v1/kb/x"]);
  });

  it("has no hand-rolled proxy that drops the header", () => {
    const dropping = routeFiles
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        if (source.includes("platformProxy")) return false;
        if (source.includes("X-Organization-Id")) return false;
        return forwardedBackendPaths(source).some((backendPath) =>
          ORG_SCOPED_BACKEND_PREFIXES.some((prefix) => backendPath.startsWith(prefix)),
        );
      })
      .map((path) => path.slice(APP_ROOT.length + 1))
      .sort();

    expect(dropping).toEqual([]);
  });
});

// -- is every interpolated path segment encoded? ------------------------------

/**
 * Path segments a hand-rolled proxy interpolates into a `/api/v1` template
 * without encoding.
 *
 * `${x}` immediately after a `/` inside a versioned-API template literal is a
 * path segment, and `%2f`/`%2e%2e` in the raw value decode and normalise there:
 * `x%2F..%2F..%2Fopenapi.json` reaches the backend as a different path (#13,
 * #30). The host prefix (`${BACKEND_URL}`, before `/api/v1`) and the query
 * (`${...search}`, `${qs}` - never after a `/`) are not segments and not
 * matched. A route built on the shared platformProxy forwards `nextUrl.pathname`
 * verbatim, so it interpolates nothing here and is left alone.
 */
function unencodedSegments(source: string): string[] {
  const offenders: string[] = [];
  for (const template of source.match(/`[^`]*\/api\/v1\/[^`]*`/g) ?? []) {
    for (const match of template.matchAll(/\/\$\{([^{}]+)\}/g)) {
      const expr = (match[1] ?? "").trim();
      if (!expr.startsWith("encodeURIComponent")) offenders.push(expr);
    }
  }
  return offenders;
}

describe("every hand-rolled proxy encodes its path segments", () => {
  const routeFiles = sourceFiles(APP_ROOT, (name) => name.endsWith("route.ts"));

  it("recognises a bare segment, an encoded one, and a query", () => {
    expect(unencodedSegments("fetch(`/api/v1/orgs/${id}`)")).toEqual(["id"]);
    expect(unencodedSegments("fetch(`/api/v1/orgs/${encodeURIComponent(id)}`)")).toEqual([]);
    expect(unencodedSegments("fetch(`${BACKEND_URL}/api/v1/x${request.nextUrl.search}`)")).toEqual(
      [],
    );
  });

  it("has no hand-rolled proxy interpolating a bare segment", () => {
    const offenders = routeFiles
      .filter((path) => unencodedSegments(readFileSync(path, "utf8")).length > 0)
      .map((path) => path.slice(APP_ROOT.length + 1))
      .sort();

    expect(offenders).toEqual([]);
  });
});

// -- is there a route behind every path the client calls? ---------------------

/**
 * Whether a BFF path resolves to a route file, following Next's own rules.
 *
 * A literal directory wins over a dynamic one, `[slug]` takes exactly one
 * segment, `[...slug]` takes one or more and `[[...slug]]` takes any number
 * including none. Resolving the *whole* path rather than its first segment is
 * the point: `/rag/supported-formats` had a `rag` directory and no route behind
 * that path, which is a 404 the old first-segment check called a pass.
 */
function isRouted(path: string): boolean {
  const segments =
    path
      .replace(/^\/api/, "")
      .split("?")[0]
      ?.split("/")
      .filter(Boolean) ?? [];

  const resolve = (directory: string, remaining: string[]): boolean => {
    let entries: string[];
    try {
      entries = readdirSync(directory);
    } catch {
      return false;
    }
    const optionalCatchAll = entries.some((entry) => entry.startsWith("[[..."));
    const catchAll = entries.some((entry) => entry.startsWith("[..."));
    const [head, ...tail] = remaining;

    if (head === undefined) return optionalCatchAll || entries.includes("route.ts");
    if (optionalCatchAll || catchAll) return true;
    if (entries.includes(head) && resolve(join(directory, head), tail)) return true;
    const slug = entries.find((entry) => entry.startsWith("[") && !entry.includes("..."));
    return slug !== undefined && resolve(join(directory, slug), tail);
  };

  return resolve(APP_ROOT, segments);
}

/**
 * Every BFF path the client asks for.
 *
 * Two forms, because the app writes both: a path handed to `apiClient`, which
 * prefixes `/api` itself, and an absolute `/api/...` string given to `fetch`,
 * `XMLHttpRequest` or an `<a href>` - the download links, which no hook ever
 * touches. Newlines are collapsed first so a method call split across lines by
 * the formatter still matches.
 */
function calledPaths(): Set<string> {
  const paths = new Set<string>();
  const files = sourceFiles(
    SRC,
    (name) => /\.tsx?$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".test.tsx"),
  ).filter((path) => !path.startsWith(APP_ROOT));
  for (const file of files) {
    // `backendFetch` takes a *backend* path, not a BFF one, and there is no
    // route file behind `/api/v1/...` here by design - those calls run on the
    // server and go straight to FastAPI. Dropping the argument keeps them out
    // without having to exempt `/api/v1` wholesale, which is what let
    // `<a href="/api/v1/agents/{id}/spec.yaml">` 404 unnoticed.
    const source = readFileSync(file, "utf8")
      .replace(/backendFetch\s*(?:<[^>]*>)?\(\s*[`"][^`"]*[`"]/g, "backendFetch(")
      .replace(/\s+/g, " ");
    for (const match of source.matchAll(/apiClient\s*\.\s*\w+(?:<[^>]*>)?\(\s*[`"](\/[^`"]*)/g)) {
      paths.add(`/api${match[1] ?? ""}`);
    }
    for (const match of source.matchAll(/[`"](\/api\/[^`"\s]*)/g)) {
      paths.add(match[1] ?? "");
    }
  }
  // `${...}` is a path parameter; the resolver only needs to know a segment is
  // there. A bare `/api/*` or `/api/<path>` is prose from a comment.
  return new Set(
    [...paths]
      .map((path) => path.replace(/\$\{[^}]*\}/g, "x").split("?")[0] ?? "")
      .filter((path) => /^\/api\/[\w[\]./-]*$/.test(path)),
  );
}

/**
 * Paths the client asks for on purpose that no route answers, and why.
 *
 * A call to an endpoint the backend has never had, made by a page that handles
 * the 404 explicitly - a message naming the missing endpoint. Listed rather
 * than deleted because the UI it belongs to is real; listed rather than
 * ignored because "the client calls something that does not exist" is
 * otherwise exactly the thing this sweep is for.
 */
const CALLED_WITHOUT_AN_ENDPOINT: ReadonlySet<string> = new Set([
  // Settings → Account. The form is built; the backend endpoint is not, and the
  // page says so in the toast it shows on the 404.
  "/api/auth/password/change",
]);

describe("every endpoint the client calls is proxied", () => {
  it("finds the calls it is supposed to be checking", () => {
    // Without this the guard below passes when the regex stops matching -
    // vacuously green, which is exactly the failure it exists to prevent.
    const paths = calledPaths();

    expect(paths.size).toBeGreaterThan(20);
    expect(paths).toContain("/api/agents");
    expect(paths).toContain("/api/rag/search");
    expect(paths).toContain("/api/kb");
  });

  it("has no stale entries in the list of paths with no endpoint", () => {
    const routed = [...CALLED_WITHOUT_AN_ENDPOINT].filter(isRouted).sort();

    expect(routed).toEqual([]);
  });

  it("notices a path that has no route", () => {
    expect(isRouted("/api/definitely-not-mounted")).toBe(false);
    expect(isRouted("/api/kb")).toBe(true);
    expect(isRouted("/api/kb/x/documents/y/download")).toBe(true);
  });

  it("has a route file behind every path the client asks for", () => {
    const unrouted = [...calledPaths()]
      .filter((path) => !isRouted(path) && !CALLED_WITHOUT_AN_ENDPOINT.has(path))
      .sort();

    expect(unrouted).toEqual([]);
  });
});
