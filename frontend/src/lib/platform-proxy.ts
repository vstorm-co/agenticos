/**
 * One proxy for the whole platform API surface.
 *
 * The browser never talks to the backend directly - it calls `/api/*` on this
 * app, which forwards to FastAPI with the access token taken from an HttpOnly
 * cookie. That is what keeps the token out of JavaScript and the backend URL
 * out of the client bundle.
 *
 * The generated template writes one hand-rolled route file per endpoint, each
 * repeating the same twelve lines. The platform surface - agents, runs,
 * approvals, skills, providers, roles, sharing - is upwards of thirty
 * endpoints that differ in nothing but their path, so it gets one forwarder
 * instead: fewer places for a header to be forgotten, and a new backend route
 * needs no frontend change at all.
 *
 * "Fewer places for a header to be forgotten" is not a figure of speech. The
 * hand-rolled routes under `/kb` and `/rag` forwarded the token and not the
 * active organization, so every request from those two pages resolved against
 * the caller's *personal* organization while the UI showed another one - an
 * empty list, on a page whose data plainly exists. That is why they are on this
 * forwarder now, and why anything else calling an org-scoped endpoint has to be
 * too: `platform-proxy.test.ts` fails the build otherwise.
 *
 * Three things it does that a hand-rolled route usually forgets. It returns the
 * backend's own status and body, so a 403 from the permission layer reaches the
 * UI as a 403 with its message rather than a generic failure - the difference
 * between "you cannot do this" and "something broke". It forwards the active
 * organization header, without which every org-scoped request would silently
 * answer for the user's personal organization instead of the one the UI is
 * showing. And it moves bodies as bytes rather than text, in both directions,
 * so a file upload keeps its multipart boundary and a downloaded PDF arrives as
 * the bytes the backend sent.
 */

import { NextRequest, NextResponse } from "next/server";

import { bffRefusal } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const ORG_HEADER = "X-Organization-Id";

/** Methods that carry a body. Anything else forwards without reading one. */
const WITH_BODY = new Set(["POST", "PUT", "PATCH"]);

/**
 * Response headers that describe the body and must survive the hop.
 *
 * A proxy forwards what the origin said rather than inventing a policy of its
 * own: `Content-Disposition` is how a download gets its filename, and a
 * `Cache-Control` the backend chose - the catalog icons, an embed bundle - is
 * the backend's decision to make.
 */
const DESCRIBES_THE_BODY = ["content-type", "content-disposition", "cache-control"];

/**
 * What a response gets when the backend named no policy at all.
 *
 * Silence is not the same as "do not cache". A 200 with no `Cache-Control`, no
 * `ETag` and no `Last-Modified` is a response the browser may reuse on its own
 * judgement, and every mutable collection on this surface arrived that way - so a
 * list refetched immediately after a write could be answered without the server
 * being asked, and the page went on rendering the row it had just created as
 * absent (#230). Nothing here is cacheable by default anyway: every answer
 * depends on the caller's cookie, their permissions and the organization header,
 * which is the same reason the outbound `fetch` below is `no-store`.
 */
const NO_POLICY_MEANS = "no-store";

type Handler = (request: NextRequest) => Promise<Response>;

/** The route exports Next expects. Named, not a `Record`, so a caller reaching
 * for `.GET` gets a function rather than a possibly-undefined one. */
export type ProxyHandlers = {
  GET: Handler;
  POST: Handler;
  PUT: Handler;
  PATCH: Handler;
  DELETE: Handler;
};

function describingHeaders(source: Headers): Headers {
  const headers = new Headers();
  for (const name of DESCRIBES_THE_BODY) {
    const value = source.get(name);
    if (value) headers.set(name, value);
  }
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  if (!headers.has("cache-control")) headers.set("cache-control", NO_POLICY_MEANS);
  return headers;
}

/**
 * Handlers forwarding `/api/<path>` to `/api/v1/<path>`, unchanged.
 *
 * The path is taken from the request rather than passed in, so mounting this
 * at a new place needs no argument to keep in sync with the directory it sits
 * in - the one thing that would silently send a route to the wrong endpoint.
 */
export function platformProxy(): ProxyHandlers {
  const forward: Handler = async (request) => {
    const accessToken = request.cookies.get("access_token")?.value;
    if (!accessToken) {
      return bffRefusal("NOT_AUTHENTICATED", 401);
    }

    const path = request.nextUrl.pathname.replace(/^\/api/, "");
    const url = `${BACKEND_URL}/api/v1${path}${request.nextUrl.search}`;

    const organizationId = request.headers.get(ORG_HEADER);
    // The caller's own content type rather than a fixed one: a file upload is
    // multipart with a boundary only the browser knows, and rewriting that to
    // `application/json` makes FastAPI reject the body it was just handed.
    const contentType = request.headers.get("content-type");

    const response = await fetch(url, {
      method: request.method,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(contentType ? { "Content-Type": contentType } : {}),
        ...(organizationId ? { [ORG_HEADER]: organizationId } : {}),
      },
      // The request's own stream, not `await request.arrayBuffer()`: a 50 MB
      // upload buffered whole in this process before one byte reaches FastAPI is
      // memory the container's limit decides the fate of, and streaming keeps
      // the bytes bytes without holding them. `duplex: "half"` is undici's
      // requirement for a streamed request body and is not yet in the DOM
      // `RequestInit` type, hence the cast.
      body: WITH_BODY.has(request.method) ? request.body : undefined,
      duplex: "half",
      // A proxy must never serve a cached answer: the reply depends on the
      // caller's role and on rows that change under them.
      cache: "no-store",
    } as RequestInit & { duplex: "half" });

    // The backend's own body stream, passed through rather than buffered: a 204
    // carries a null body and stays empty, an error body reaches the client
    // exactly as the backend wrote it, and a large download reaches the browser
    // as it arrives rather than only once the last byte is here. Re-reading it
    // is how `detail` goes missing from a refusal and time-to-first-byte becomes
    // the whole transfer.
    return new NextResponse(response.body, {
      status: response.status,
      headers: describingHeaders(response.headers),
    });
  };

  return { GET: forward, POST: forward, PUT: forward, PATCH: forward, DELETE: forward };
}
