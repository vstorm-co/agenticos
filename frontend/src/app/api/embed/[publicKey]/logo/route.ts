import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// The key is minted with `secrets.token_urlsafe`, so anything outside that
// alphabet is not one this deployment ever issued. Validated rather than only
// encoded, for the reason the avatar route beside this one gives: this route takes
// a client-controlled path segment and checks no cookie - deliberately, because a
// hosted page's logo is public - so a malformed segment must never reach the
// network at all.
const KEY_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

// What this route will pass on. Echoing the backend's own answer is what the other
// proxies here do, and it is wrong on this one: this response is served from the
// origin the hosted page runs on, under a policy that allows `'unsafe-inline'`
// script, so `text/html` or `image/svg+xml` here is a script on that origin rather
// than a picture on the page. The backend pins the type too - both ends, because
// each is one line and either alone is a single point of failure for a stored XSS.
const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/gif"]);

/**
 * A hosted page's logo, served from this origin.
 *
 * The page used to point an `<img>` straight at the API, and the browser refused
 * it: `img-src 'self' blob: data: https:` in `next.config.ts` excludes an API on
 * plain `http`, which is every development checkout and any self-hosted deployment
 * that terminates TLS elsewhere. The result was a broken-image glyph in the header
 * and in every assistant turn's gutter, with nothing in the UI saying why.
 *
 * Proxied rather than answered by widening the policy, because the policy is not
 * the thing that is wrong: an image on a page we serve should come from the origin
 * serving it, and then it works whatever host the API is on. `connect-src` already
 * carries a `http://localhost:*` exception for exactly this shape, and this route
 * is what makes a second one unnecessary.
 *
 * Cached briefly, like the widget script: the logo is edited in the Builder, and a
 * day-long cache would make a change look like it did not save.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ publicKey: string }> },
) {
  const { publicKey } = await params;
  if (!KEY_PATTERN.test(publicKey)) {
    return new NextResponse(null, { status: 400 });
  }

  try {
    const response = await fetch(
      `${BACKEND_URL}/api/v1/embed/${encodeURIComponent(publicKey)}/logo`,
    );
    if (!response.ok) {
      return new NextResponse(null, { status: response.status });
    }
    const type = response.headers.get("content-type")?.split(";")[0]?.trim() ?? "";
    if (!IMAGE_TYPES.has(type)) {
      return new NextResponse(null, { status: 502 });
    }
    return new NextResponse(await response.arrayBuffer(), {
      headers: {
        "Content-Type": type,
        "Cache-Control": "public, max-age=300",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new NextResponse(null, { status: 502 });
  }
}
