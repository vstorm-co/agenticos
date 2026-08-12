/**
 * @vitest-environment node
 *
 * These are server routes. The suite's default environment is jsdom, where
 * `request.formData()` never resolves - the multipart parser wants a real
 * stream - and running route handlers in a browser-shaped global is a lie about
 * where they execute anyway.
 */
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST as uploadFile } from "./files/upload/route";
import { GET as readFile } from "./files/[id]/route";
import { GET as callback } from "./me/mcp-connections/oauth/callback/route";
import { GET as orgAvatar, POST as setOrgAvatar } from "./orgs/[id]/avatar/route";
import { GET as hostedLogo } from "./embed/[publicKey]/logo/route";
import { GET as userAvatar } from "./users/avatar/[userId]/route";
import { POST as setOwnAvatar } from "./users/me/avatar/route";
import { backendFetch } from "@/lib/server-api";

vi.mock("@/lib/server-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/server-api")>("@/lib/server-api");
  return { ...actual, backendFetch: vi.fn() };
});

let fetchMock: ReturnType<typeof vi.fn>;

/** What the backend answers with, as a real `Response` so bytes stay bytes. */
function serve(
  body: BodyInit | null,
  { status = 200, headers = {} }: { status?: number; headers?: Record<string, string> } = {},
) {
  fetchMock = vi.fn().mockResolvedValue(new Response(body, { status, headers }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function request(
  url: string,
  { signedIn = true, form }: { signedIn?: boolean; form?: FormData } = {},
): NextRequest {
  if (!form) {
    return new NextRequest(url, { headers: signedIn ? { cookie: "access_token=at" } : {} });
  }
  // Built as a plain `Request` first so the multipart boundary lands in the
  // content type; a `formData()` call with no boundary never resolves.
  const withBody = new Request(url, { method: "POST", body: form });
  const headers = new Headers(withBody.headers);
  if (signedIn) headers.set("cookie", "access_token=at");
  return new NextRequest(new Request(withBody, { headers }));
}

function file(name = "invoice.pdf") {
  const form = new FormData();
  form.append("file", new File(["bytes"], name, { type: "application/pdf" }));
  return form;
}

beforeEach(() => {
  vi.clearAllMocks();
  serve("{}", { headers: { "content-type": "application/json" } });
});

afterEach(() => vi.unstubAllGlobals());

/**
 * The routes that move bytes rather than JSON.
 *
 * They exist outside the shared proxy because each has something of its own to
 * do - forward a multipart body, set a caching policy, override a frame
 * policy - and what they share is the failure mode: decoding a body to text and
 * back silently corrupts every file that goes through, and a re-serialized
 * response loses the headers a download depends on.
 */
describe("uploading a file to a conversation", () => {
  it("forwards the multipart body as it arrived, with the caller's token", async () => {
    // Not re-encoded: only the browser knows the boundary in the body it built.
    serve(JSON.stringify({ id: "f-1" }), { headers: { "content-type": "application/json" } });

    const response = await uploadFile(
      request("http://localhost:3000/api/files/upload", { form: file() }),
    );

    expect(response.status).toBe(201);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("http://localhost:8000/api/v1/files/upload");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer at");
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("refuses an upload from somebody with no session", async () => {
    const response = await uploadFile(
      request("http://localhost:3000/api/files/upload", { form: file(), signedIn: false }),
    );

    expect(response.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the backend's own refusal through, body and status", async () => {
    // "File exceeds 50 MB" is the sentence the chat shows.
    serve(JSON.stringify({ detail: "File exceeds 50 MB" }), {
      status: 413,
      headers: { "content-type": "application/json" },
    });

    const response = await uploadFile(
      request("http://localhost:3000/api/files/upload", { form: file() }),
    );

    expect(response.status).toBe(413);
    await expect(response.json()).resolves.toEqual({ detail: "File exceeds 50 MB" });
  });

  it("still says the upload failed when the refusal is not JSON", async () => {
    serve("<html>Gateway Timeout</html>", {
      status: 504,
      headers: { "content-type": "text/html" },
    });

    const response = await uploadFile(
      request("http://localhost:3000/api/files/upload", { form: file() }),
    );

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toEqual({ detail: "Upload failed" });
  });

  it("answers 500 when the backend could not be reached", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await uploadFile(
      request("http://localhost:3000/api/files/upload", { form: file() }),
    );

    expect(response.status).toBe(500);
  });
});

describe("reading a file back", () => {
  const params = { params: Promise.resolve({ id: "f-1" }) };

  it("answers with the bytes, the type and the filename the backend chose", async () => {
    // The filename lives in `Content-Disposition`; losing it saves the file as
    // its id, which is a file nobody can find again.
    serve("%PDF-1.7", {
      headers: {
        "content-type": "application/pdf",
        "content-disposition": 'inline; filename="invoice.pdf"',
      },
    });

    const response = await readFile(request("http://localhost:3000/api/files/f-1"), params);

    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toBe('inline; filename="invoice.pdf"');
    await expect(response.text()).resolves.toBe("%PDF-1.7");
  });

  it("lets the preview panel embed it, against the app's own global refusal", async () => {
    // `next.config.ts` sets `X-Frame-Options: DENY` for every response; without
    // this override Firefox refuses to render the chat's own preview iframe.
    serve("%PDF-1.7", { headers: { "content-type": "application/pdf" } });

    const response = await readFile(request("http://localhost:3000/api/files/f-1"), params);

    expect(response.headers.get("x-frame-options")).toBe("SAMEORIGIN");
    expect(response.headers.get("content-security-policy")).toBe("frame-ancestors 'self'");
  });

  it("forwards the disposition the caller asked for, which is what Download uses", async () => {
    serve("bytes");

    await readFile(request("http://localhost:3000/api/files/f-1?disposition=attachment"), params);

    expect(fetchMock.mock.calls[0]![0]).toBe(
      "http://localhost:8000/api/v1/files/f-1?disposition=attachment",
    );
  });

  it("asks for the file plainly when nothing was asked for", async () => {
    serve("bytes");

    await readFile(request("http://localhost:3000/api/files/f-1"), params);

    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/v1/files/f-1");
  });

  it("falls back to a generic type rather than guessing one", async () => {
    // A backend that named no type at all - which is what a streamed response
    // from storage looks like.
    serve("bytes", { headers: { "content-type": "" } });

    const response = await readFile(request("http://localhost:3000/api/files/f-1"), params);

    expect(response.headers.get("content-type")).toBe("application/octet-stream");
    expect(response.headers.get("content-disposition")).toBe("");
  });

  it("refuses without a session, and reports what the backend refused", async () => {
    const anonymous = await readFile(
      request("http://localhost:3000/api/files/f-1", { signedIn: false }),
      params,
    );
    expect(anonymous.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();

    serve(null, { status: 404 });
    const missing = await readFile(request("http://localhost:3000/api/files/f-1"), params);
    expect(missing.status).toBe(404);
    await expect(missing.json()).resolves.toEqual({ detail: "File not found" });
  });

  it("answers 500 when the backend could not be reached", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await readFile(request("http://localhost:3000/api/files/f-1"), params);

    expect(response.status).toBe(500);
  });
});

// The backend signature is `user_id: UUID`, and the route now says so. A
// placeholder like "u-1" was never a value this endpoint could serve.
const AVATAR_USER = "8f14e45f-ceea-4a67-b1e6-6c1f2b1f4a3d";

describe("avatars", () => {
  it("serves a person's avatar to anybody, because a picture is not a secret", async () => {
    // No session: the chat renders avatars for every participant, and gating them
    // would mean a page of empty circles for anybody but the caller.
    serve("jpeg-bytes", { headers: { "content-type": "image/png" } });

    const response = await userAvatar(
      request(`http://localhost:3000/api/users/avatar/${AVATAR_USER}`),
      {
        params: Promise.resolve({ userId: AVATAR_USER }),
      },
    );

    expect(fetchMock.mock.calls[0]![0]).toBe(
      `http://localhost:8000/api/v1/users/avatar/${AVATAR_USER}`,
    );
    expect(response.headers.get("content-type")).toBe("image/png");
    // Never cached: a replaced picture has the same URL as the old one.
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("assumes a JPEG when the backend named no type", async () => {
    serve("bytes", { headers: { "content-type": "" } });

    const response = await userAvatar(
      request(`http://localhost:3000/api/users/avatar/${AVATAR_USER}`),
      {
        params: Promise.resolve({ userId: AVATAR_USER }),
      },
    );

    expect(response.headers.get("content-type")).toBe("image/jpeg");
  });

  it("answers with nothing at all for a person who has no picture", async () => {
    // An empty body rather than a JSON error: this URL is an `<img src>`, and a
    // JSON body there renders as a broken image with a parse error in the console.
    serve(null, { status: 404 });

    const response = await userAvatar(
      request(`http://localhost:3000/api/users/avatar/${AVATAR_USER}`),
      {
        params: Promise.resolve({ userId: AVATAR_USER }),
      },
    );

    expect(response.status).toBe(404);
    await expect(response.text()).resolves.toBe("");
  });

  it("answers with nothing when the backend could not be reached", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await userAvatar(
      request(`http://localhost:3000/api/users/avatar/${AVATAR_USER}`),
      {
        params: Promise.resolve({ userId: AVATAR_USER }),
      },
    );

    expect(response.status).toBe(500);
    await expect(response.text()).resolves.toBe("");
  });

  it("cannot be walked out of its own path segment", async () => {
    // The defect: the segment was interpolated raw. Next decodes `%2F` into the
    // param and `fetch` then normalises `..`, so this reached the backend as
    // `GET /api/v1/openapi.json` - from an anonymous caller, because avatars
    // are deliberately served without a cookie. Everything the backend answers
    // without an Authorization header became public and un-throttled.
    serve("bytes");

    const response = await userAvatar(request("http://localhost:3000/api/users/avatar/traversal"), {
      params: Promise.resolve({ userId: "x/../../../openapi.json" }),
    });

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a segment carrying a query string", async () => {
    serve("bytes");

    const response = await userAvatar(request("http://localhost:3000/api/users/avatar/traversal"), {
      params: Promise.resolve({ userId: "../../../health?probe=1" }),
    });

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uploads the caller's own picture as multipart", async () => {
    serve(JSON.stringify({ avatar_url: "/api/users/avatar/u-1" }), {
      headers: { "content-type": "application/json" },
    });

    const response = await setOwnAvatar(
      request("http://localhost:3000/api/users/me/avatar", { form: file("face.png") }),
    );

    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/v1/users/me/avatar");
    expect(fetchMock.mock.calls[0]![1].body).toBeInstanceOf(FormData);
    await expect(response.json()).resolves.toMatchObject({ avatar_url: expect.any(String) });
  });

  it("refuses an avatar upload with no session, and reports a rejected one", async () => {
    const anonymous = await setOwnAvatar(
      request("http://localhost:3000/api/users/me/avatar", { form: file(), signedIn: false }),
    );
    expect(anonymous.status).toBe(401);

    serve(JSON.stringify({ detail: "That file is too large" }), {
      status: 413,
      headers: { "content-type": "application/json" },
    });
    const rejected = await setOwnAvatar(
      request("http://localhost:3000/api/users/me/avatar", { form: file() }),
    );
    expect(rejected.status).toBe(413);
    await expect(rejected.json()).resolves.toEqual({ detail: "That file is too large" });
  });

  it("still says an avatar upload failed when the refusal is not JSON", async () => {
    serve("<html>Bad Gateway</html>", { status: 502, headers: { "content-type": "text/html" } });

    const response = await setOwnAvatar(
      request("http://localhost:3000/api/users/me/avatar", { form: file() }),
    );

    await expect(response.json()).resolves.toEqual({ detail: "Upload failed" });
  });

  it("answers 500 when an avatar upload could not be attempted", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await setOwnAvatar(
      request("http://localhost:3000/api/users/me/avatar", { form: file() }),
    );

    expect(response.status).toBe(500);
  });

  it("reads an organization's avatar with the caller's token, and caches it briefly", async () => {
    // Unlike a person's, this one is behind the session: it says which
    // organizations exist.
    serve("bytes", { headers: { "content-type": "image/png" } });

    const response = await orgAvatar(request("http://localhost:3000/api/orgs/org 1/avatar"), {
      params: Promise.resolve({ id: "org 1" }),
    });

    expect(fetchMock.mock.calls[0]![0]).toBe("http://localhost:8000/api/v1/orgs/org%201/avatar");
    expect((fetchMock.mock.calls[0]![1].headers as Record<string, string>).Authorization).toBe(
      "Bearer at",
    );
    expect(response.headers.get("cache-control")).toBe("private, max-age=30");
  });

  it("assumes a JPEG for an organization avatar with no type", async () => {
    serve("bytes", { headers: { "content-type": "" } });

    const response = await orgAvatar(request("http://localhost:3000/api/orgs/org-1/avatar"), {
      params: Promise.resolve({ id: "org-1" }),
    });

    expect(response.headers.get("content-type")).toBe("image/jpeg");
  });

  it("refuses an organization avatar without a session, and reports a missing one", async () => {
    const anonymous = await orgAvatar(
      request("http://localhost:3000/api/orgs/org-1/avatar", { signedIn: false }),
      { params: Promise.resolve({ id: "org-1" }) },
    );
    expect(anonymous.status).toBe(401);

    serve(null, { status: 404 });
    const missing = await orgAvatar(request("http://localhost:3000/api/orgs/org-1/avatar"), {
      params: Promise.resolve({ id: "org-1" }),
    });
    expect(missing.status).toBe(404);
    await expect(missing.json()).resolves.toEqual({ detail: "Avatar not available" });
  });

  it("answers 500 when an organization avatar could not be fetched", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    const response = await orgAvatar(request("http://localhost:3000/api/orgs/org-1/avatar"), {
      params: Promise.resolve({ id: "org-1" }),
    });

    expect(response.status).toBe(500);
  });

  it("uploads an organization's picture, and passes a refusal through", async () => {
    serve(JSON.stringify({ avatar_url: "/api/orgs/org-1/avatar" }), {
      headers: { "content-type": "application/json" },
    });
    const uploaded = await setOrgAvatar(
      request("http://localhost:3000/api/orgs/org-1/avatar", { form: file("logo.png") }),
      { params: Promise.resolve({ id: "org-1" }) },
    );
    expect(fetchMock.mock.calls[0]![1].method).toBe("POST");
    expect(uploaded.status).toBe(200);

    serve(JSON.stringify({ detail: "Not your organization" }), {
      status: 403,
      headers: { "content-type": "application/json" },
    });
    const refused = await setOrgAvatar(
      request("http://localhost:3000/api/orgs/org-1/avatar", { form: file() }),
      { params: Promise.resolve({ id: "org-1" }) },
    );
    expect(refused.status).toBe(403);
  });

  it("refuses an organization avatar upload with no session, and 500s on an outage", async () => {
    const anonymous = await setOrgAvatar(
      request("http://localhost:3000/api/orgs/org-1/avatar", { form: file(), signedIn: false }),
      { params: Promise.resolve({ id: "org-1" }) },
    );
    expect(anonymous.status).toBe(401);

    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);
    const broken = await setOrgAvatar(
      request("http://localhost:3000/api/orgs/org-1/avatar", { form: file() }),
      { params: Promise.resolve({ id: "org-1" }) },
    );
    expect(broken.status).toBe(500);
  });
});

/**
 * Where a provider sends the browser back after an OAuth consent.
 *
 * No session is required and none is read: the `state` token is what
 * authenticates the exchange. Every outcome ends as a redirect to the settings
 * page carrying a status, because this URL is opened by the provider and the
 * person is looking at a page they did not navigate to themselves - a JSON body
 * here would be a dead end.
 */
describe("finishing an MCP OAuth flow", () => {
  function callbackRequest(query: string) {
    return new NextRequest(`http://localhost:3000/api/me/mcp-connections/oauth/callback?${query}`);
  }

  /** The query the redirect carries, decoded. */
  function redirected(response: Response) {
    const location = new URL(response.headers.get("location")!);
    return {
      path: location.pathname,
      status: location.searchParams.get("mcp_oauth"),
      reason: location.searchParams.get("reason"),
      name: location.searchParams.get("name"),
    };
  }

  it("names the connection it just authorized", async () => {
    vi.mocked(backendFetch).mockResolvedValue({
      ok: true,
      connection_name: "Linear",
      error: null,
    });

    const response = await callback(callbackRequest("code=abc&state=xyz"));

    expect(backendFetch).toHaveBeenCalledWith("/api/v1/me/mcp-connections/oauth/callback", {
      method: "POST",
      body: JSON.stringify({ code: "abc", state: "xyz" }),
    });
    expect(redirected(response)).toMatchObject({
      path: "/settings/integrations",
      status: "success",
      name: "Linear",
    });
  });

  it("redirects with an empty name when the backend named nothing", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ ok: true, connection_name: null, error: null });

    const response = await callback(callbackRequest("code=abc&state=xyz"));

    expect(redirected(response)).toMatchObject({ status: "success", name: "" });
  });

  it("carries the provider's own account of a refusal", async () => {
    const response = await callback(
      callbackRequest("error=access_denied&error_description=You%20said%20no"),
    );

    expect(backendFetch).not.toHaveBeenCalled();
    expect(redirected(response)).toMatchObject({ status: "error", reason: "You said no" });
  });

  it("falls back to the provider's error code when it described nothing", async () => {
    const response = await callback(callbackRequest("error=access_denied"));

    expect(redirected(response)).toMatchObject({ status: "error", reason: "access_denied" });
  });

  it("refuses a callback with no code or no state", async () => {
    // Which is what a truncated redirect or a stale bookmark looks like.
    for (const query of ["code=abc", "state=xyz", ""]) {
      const response = await callback(callbackRequest(query));

      expect(redirected(response)).toMatchObject({
        status: "error",
        reason: "Missing authorization code",
      });
    }
    expect(backendFetch).not.toHaveBeenCalled();
  });

  it("carries the backend's reason when the exchange itself was refused", async () => {
    vi.mocked(backendFetch).mockResolvedValue({
      ok: false,
      connection_name: null,
      error: "That state token has expired",
    });

    const response = await callback(callbackRequest("code=abc&state=stale"));

    expect(redirected(response)).toMatchObject({
      status: "error",
      reason: "That state token has expired",
    });
  });

  it("says authorization failed when the refusal named no reason", async () => {
    vi.mocked(backendFetch).mockResolvedValue({ ok: false, connection_name: null, error: null });

    const response = await callback(callbackRequest("code=abc&state=xyz"));

    expect(redirected(response)).toMatchObject({ reason: "Authorization failed" });
  });

  it("still redirects when the exchange could not be attempted", async () => {
    // A dead end here is a page the person cannot get out of.
    vi.mocked(backendFetch).mockRejectedValue(new Error("ECONNREFUSED"));

    const response = await callback(callbackRequest("code=abc&state=xyz"));

    expect(redirected(response)).toMatchObject({ status: "error", reason: "Authorization failed" });
  });
});

describe("a hosted page's logo", () => {
  const KEY = "W-Buc9zD7bZOzro8FYEOmOpGrNxFGuN7";

  function logo(key = KEY) {
    return hostedLogo(request(`http://localhost:3000/api/embed/${key}/logo`, { signedIn: false }), {
      params: Promise.resolve({ publicKey: key }),
    });
  }

  it("serves the image from this origin rather than from the API", async () => {
    // The whole reason the route exists. `img-src 'self' blob: data: https:`
    // excludes an API on plain `http` - every development checkout, and any
    // deployment that terminates TLS elsewhere - so a page pointing an `<img>` at
    // the API rendered a broken glyph in its header and in every turn's gutter.
    serve("PNGBYTES", { headers: { "content-type": "image/png" } });

    const response = await logo();

    expect(response.status).toBe(200);
    await expect(response.text()).resolves.toBe("PNGBYTES");
    expect(fetchMock.mock.calls[0]![0]).toBe(`http://localhost:8000/api/v1/embed/${KEY}/logo`);
  });

  it("needs no session, because the page it is on has none", async () => {
    serve("PNGBYTES", { headers: { "content-type": "image/png" } });

    await logo();

    const headers = (fetchMock.mock.calls[0]![1] ?? {}) as { headers?: Record<string, string> };
    expect(headers.headers?.cookie).toBeUndefined();
  });

  it("assumes a PNG when the backend named no type", async () => {
    serve("bytes", { headers: { "content-type": "" } });

    expect((await logo()).headers.get("content-type")).toBe("image/png");
  });

  it("lets a browser hold it briefly, because the Builder can change it", async () => {
    serve("bytes", { headers: { "content-type": "image/png" } });

    expect((await logo()).headers.get("cache-control")).toBe("public, max-age=300");
  });

  it("refuses a key outside the alphabet one is minted from, without a round trip", async () => {
    // The segment is client-controlled and this route checks no cookie, so a
    // malformed one must never reach the network - `%2F` decodes into the param and
    // `fetch` then normalises `..`, which is how such a route became a way to read
    // the backend's own endpoints.
    serve("bytes");

    const response = await logo("x%2F..%2F..%2Fopenapi.json");

    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("answers with nothing at all for a page that shows no logo", async () => {
    serve(null, { status: 404 });

    const response = await logo();

    expect(response.status).toBe(404);
    await expect(response.text()).resolves.toBe("");
  });

  it("answers 502 when the backend could not be reached", async () => {
    fetchMock = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    vi.stubGlobal("fetch", fetchMock);

    expect((await logo()).status).toBe(502);
  });
});
