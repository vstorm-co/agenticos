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

/** Skip a `'`- or `"`-quoted string from its opening quote; returns the index past its close. */
function skipQuoted(src: string, at: number): number {
  const quote = src[at];
  let i = at + 1;
  while (i < src.length) {
    if (src[i] === "\\") {
      i += 2;
      continue;
    }
    if (src[i] === quote) return i + 1;
    i++;
  }
  return i;
}

/** Skip a `//` or block comment from its opening slash; returns the index past its end. */
function skipComment(src: string, at: number): number {
  if (src[at + 1] === "/") {
    const nl = src.indexOf("\n", at);
    return nl < 0 ? src.length : nl + 1;
  }
  const close = src.indexOf("*/", at + 2);
  return close < 0 ? src.length : close + 2;
}

/** Consume a whole template literal from its opening backtick; returns its text and the index past its close. */
function readTemplate(src: string, at: number): { text: string; end: number } {
  let i = at + 1;
  while (i < src.length) {
    if (src[i] === "\\") {
      i += 2;
      continue;
    }
    if (src[i] === "`") return { text: src.slice(at, i + 1), end: i + 1 };
    if (src[i] === "$" && src[i + 1] === "{") {
      i = skipInterpolation(src, i);
      continue;
    }
    i++;
  }
  return { text: src.slice(at), end: src.length };
}

/**
 * Skip a `${...}` interpolation from its `$`; returns the index past its closing `}`.
 *
 * Brace depth is counted only outside string literals, and a nested template is
 * consumed whole - so a `{` inside a quoted argument (`replace("{", "")`) or a
 * nested query template does not throw the count off and absorb the segment
 * after it (#1133).
 */
function skipInterpolation(src: string, at: number): number {
  let depth = 0;
  let i = at + 1; // at the '{'
  while (i < src.length) {
    const ch = src[i];
    if (ch === "\\") {
      i += 2;
      continue;
    }
    if (ch === "'" || ch === '"') {
      i = skipQuoted(src, i);
      continue;
    }
    if (ch === "`") {
      i = readTemplate(src, i).end;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i + 1;
    }
    i++;
  }
  return i;
}

/** Every top-level template literal in the source, each consumed whole (nested templates included). */
function templateLiterals(source: string): string[] {
  const templates: string[] = [];
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    // Before the quote check, because prose is full of apostrophes: an `'` in a
    // comment otherwise opens a string that `skipQuoted` runs to the next one,
    // swallowing whatever lies between. `admin/conversations/route.ts` says
    // "drawer's" in a comment, and its `/api/v1/admin/conversations` template
    // was invisible to this sweep because of it - a security guard reporting
    // clean on a file it never read (#1133).
    if (ch === "/" && (source[i + 1] === "/" || source[i + 1] === "*")) {
      i = skipComment(source, i);
      continue;
    }
    if (ch === "'" || ch === '"') {
      i = skipQuoted(source, i);
      continue;
    }
    if (ch === "`") {
      const { text, end } = readTemplate(source, i);
      templates.push(text);
      i = end;
      continue;
    }
    i++;
  }
  return templates;
}

/**
 * Path segments a hand-rolled proxy interpolates into a `/api/v1` template
 * without encoding.
 *
 * Every `${x}` in the path portion of a versioned-API template literal is a
 * path segment - segment-leading (`/${id}`) or composite (`prefix-${id}`) alike
 * - and `%2f`/`%2e%2e` in the raw value decode and normalise there:
 * `x%2F..%2F..%2Fopenapi.json` reaches the backend as a different path (#13, #30,
 * #1118). The host prefix (`${BACKEND_URL}`, before `/api/v1`) and the query are
 * not segments - see `pathInterpolations` for where the query begins. A route
 * built on the shared platformProxy forwards `nextUrl.pathname` verbatim, so it
 * interpolates nothing here and is left alone.
 */
function unencodedSegments(source: string): string[] {
  const offenders: string[] = [];
  for (const template of templateLiterals(source)) {
    // At a boundary rather than requiring the following slash to be literal:
    // a proxy building `/api/v1${rawPath}` puts its interpolation directly
    // after the prefix, and a slash-bearing value there switches path exactly
    // as a later segment does (#1133).
    if (!/\/api\/v1(\/|\$\{|`|$)/.test(template)) continue;
    for (const expr of pathInterpolations(template)) {
      if (!isFullyEncoded(expr)) offenders.push(expr);
    }
  }
  return offenders;
}

/**
 * Whether the whole expression is one `encodeURIComponent(...)` around the whole value.
 *
 * `startsWith` is not enough: it accepts `encodeURIComponent(id) + rawSuffix`,
 * where a slash-bearing suffix rebuilds the traversal this sweep exists to
 * catch, and it accepts a look-alike name like `encodeURIComponentAlias(rawId)`.
 * So the call must open the expression, its parentheses must balance to the very
 * end, and nothing may follow (#1133).
 */
function isFullyEncoded(expr: string): boolean {
  const call = "encodeURIComponent(";
  if (!expr.startsWith(call)) return false;
  let depth = 0;
  for (let i = call.length - 1; i < expr.length; i++) {
    if (expr[i] === "(") depth++;
    else if (expr[i] === ")") {
      depth--;
      // Closed before the end, so something is appended to the encoded value.
      if (depth === 0) return i === expr.length - 1;
    }
  }
  return false;
}

/**
 * The interpolation expressions in a template's path portion, in order.
 *
 * Scanning starts at `/api/v1`, so the host prefix (`${BACKEND_URL}`) is not a
 * segment. It stops at the query, and only at something that PROVABLY starts one:
 * a literal `?` in the path text, an interpolation building a `` `?...` `` query
 * template, or a `.search` string. A `?` in a ternary or `??`, or a parameter
 * named `search`/`qs`/`query`, is a path expression and is still reported - a
 * segment that reaches the backend must be encoded whatever it is called (#1133).
 * Interpolations are string-aware brace-matched, so a `{` in a quoted argument or
 * a nested template does not absorb the segment that follows.
 */
function pathInterpolations(template: string): string[] {
  const exprs: string[] = [];
  let i = template.indexOf("/api/v1");
  if (i < 0) return exprs;
  for (; i < template.length; i++) {
    if (template[i] === "?") break; // a literal query separator: the rest is query
    if (template[i] === "$" && template[i + 1] === "{") {
      const end = skipInterpolation(template, i);
      const expr = template.slice(i + 2, end - 1).trim();
      i = end - 1;
      if (/`\?/.test(expr) || /\b(?:nextUrl|url|location)\.search\b/.test(expr)) break;
      exprs.push(expr);
    }
  }
  return exprs;
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

  it("catches an interpolation mid-segment, not only after a slash (#1118)", () => {
    // `x/../../admin` in a composite segment normalises into another backend
    // path just as a segment-leading one does, so the guard must flag it too.
    expect(unencodedSegments("fetch(`/api/v1/resources/prefix-${id}`)")).toEqual(["id"]);
    expect(
      unencodedSegments("fetch(`/api/v1/resources/prefix-${encodeURIComponent(id)}`)"),
    ).toEqual([]);
  });

  it("does not mistake a query attachment for a bare segment", () => {
    // The sessions-route ternary builds its own `?...`; its inner `${query}` and
    // the trailing `${qs}` are query, not path, so neither is an offender.
    expect(unencodedSegments('fetch(`/api/v1/sessions${query ? `?${query}` : ""}`)')).toEqual([]);
    expect(unencodedSegments("fetch(`/api/v1/sessions?${qs}`)")).toEqual([]);
  });

  it("does not let optional chaining hide a later segment", () => {
    // `?.` is not a query separator, so scanning must not stop at it - both the
    // optional-chained segment and the plain one after it stay in view.
    expect(unencodedSegments("fetch(`/api/v1/x/${a?.b}/${rawId}`)")).toEqual(["a?.b", "rawId"]);
  });

  it("reports a path expression that merely contains a query-ish token (#1133)", () => {
    // A ternary, `??`, or a parameter named search/qs/query is still a path
    // segment that reaches the backend - only a proven query separator is skipped.
    expect(unencodedSegments("fetch(`/api/v1/x/${admin ? adminId : userId}`)")).toEqual([
      "admin ? adminId : userId",
    ]);
    expect(unencodedSegments("fetch(`/api/v1/x/${kind ?? rawId}`)")).toEqual(["kind ?? rawId"]);
    expect(unencodedSegments("fetch(`/api/v1/x/${search}`)")).toEqual(["search"]);
  });

  it("does not truncate a nested template and lose a later segment (#1133)", () => {
    // The path ternary embeds a nested template `-${safe}`; both it and the plain
    // `${rawId}` after it must still be seen, not cut off at the inner backtick.
    expect(unencodedSegments('fetch(`/api/v1/x${flag ? `-${safe}` : ""}/${rawId}`)')).toEqual([
      'flag ? `-${safe}` : ""',
      "rawId",
    ]);
  });

  it("does not miscount braces inside a quoted argument (#1133)", () => {
    // The `"{"` inside `.replace` must not leave the brace counter one deep and
    // swallow `${rawId}` into the encodeURIComponent expression above it.
    expect(
      unencodedSegments('fetch(`/api/v1/x/${encodeURIComponent(id.replace("{", ""))}/${rawId}`)'),
    ).toEqual(["rawId"]);
  });

  it("reads a file whose comments contain apostrophes (#1133)", () => {
    // An `'` in prose is not a string opener. Treating it as one ran the scanner
    // to the next apostrophe and swallowed everything between - including the
    // template - so the sweep reported clean on a file it had never read.
    const source = [
      "// the admin drawer's recent-threads list",
      "fetch(`/api/v1/x/${rawId}`)",
    ].join("\n");
    expect(unencodedSegments(source)).toEqual(["rawId"]);
    expect(
      unencodedSegments("/* a block comment's apostrophe */\nfetch(`/api/v1/x/${rawId}`)"),
    ).toEqual(["rawId"]);
    // And a quote inside a comment still does not hide a later real string.
    expect(unencodedSegments("// don't\nconst s = 'x';\nfetch(`/api/v1/x/${rawId}`)")).toEqual([
      "rawId",
    ]);
  });

  it("requires the encoding call to wrap the whole value (#1133)", () => {
    // A suffix appended after the call is unencoded, and a slash in it rebuilds
    // the traversal; a look-alike function name is not the call at all.
    expect(unencodedSegments("fetch(`/api/v1/x/${encodeURIComponent(id) + rawSuffix}`)")).toEqual([
      "encodeURIComponent(id) + rawSuffix",
    ]);
    expect(unencodedSegments("fetch(`/api/v1/x/${encodeURIComponentAlias(rawId)}`)")).toEqual([
      "encodeURIComponentAlias(rawId)",
    ]);
    // The genuine article, nested parentheses included, is still clean.
    expect(unencodedSegments("fetch(`/api/v1/x/${encodeURIComponent(String(id))}`)")).toEqual([]);
  });

  it("does not read an ordinary .search property as the query (#1133)", () => {
    // Only a real URL search string ends the path. A parameter that happens to
    // expose `.search` is a path segment, and so is everything after it.
    expect(unencodedSegments("fetch(`/api/v1/x/${params.search}/${rawId}`)")).toEqual([
      "params.search",
      "rawId",
    ]);
    // A genuine URL search string still ends it.
    expect(unencodedSegments("fetch(`/api/v1/x${request.nextUrl.search}`)")).toEqual([]);
  });

  it("checks an interpolation attached straight to the version prefix (#1133)", () => {
    // `/api/v1${rawPath}` has no literal slash after the prefix, so a substring
    // test skipped the template entirely - while a slash-bearing value there
    // switches path exactly as a later segment does.
    expect(unencodedSegments("fetch(`${BACKEND_URL}/api/v1${rawPath}`)")).toEqual(["rawPath"]);
    expect(unencodedSegments("fetch(`${BACKEND_URL}/api/v1${encodeURIComponent(p)}`)")).toEqual([]);
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
