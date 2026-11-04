import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// Validated rather than only encoded, for the reason the logo route beside this
// one gives: this route takes client-controlled segments and checks no cookie, so
// a value no deployment ever minted must not reach the network at all. The key is
// `secrets.token_urlsafe`; the file is the leaf name the store wrote; the token is
// an expiry with no leading zero and a SHA-256 HMAC in hex, the one spelling the
// backend accepts (`app.services.embed_generated_media`).
const KEY_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const FILENAME_PATTERN = /^[A-Za-z0-9_-][A-Za-z0-9._-]{0,254}$/;
const TOKEN_PATTERN = /^[1-9][0-9]{0,11}\.[0-9a-f]{64}$/;

// What this route passes on: a raster image, audio or video, which a browser hands
// to its media pipeline and runs nothing from. This answer is served from the origin
// the hosted page runs on, under a policy that allows `'unsafe-inline'` script, so
// anything else - `text/html`, `image/svg+xml`, a PDF - is refused rather than
// echoed. The backend types the file from the same short list.
const MEDIA_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/gif",
  "image/webp",
  "audio/mpeg",
  "audio/wav",
  "audio/ogg",
  "audio/mp4",
  "video/mp4",
  "video/webm",
]);

/**
 * A generated image, clip of speech or video, for a visitor on a hosted page (#2309).
 *
 * The console's `/api/generated/{filename}` forwards a session cookie, and a visitor
 * has none, so their cards answered 401. This route forwards the link their socket
 * minted instead - one file, on this page, for a few hours - and the backend refuses
 * anything else with the same 404 a missing file gets.
 *
 * **Streamed, not buffered.** A clip is played from here in ranges, and reading the
 * whole answer into memory before sending any of it would hold a video in the
 * frontend server once per request. The `Range` goes up and the `206`, its
 * `Content-Range` and its length come back, because Safari plays an MP4 only from
 * ranged answers; a range past the end is a `416` that carries the length it was
 * refused against, as RFC 9110 asks.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ publicKey: string; filename: string }> },
) {
  const { publicKey, filename } = await params;
  const token = request.nextUrl.searchParams.get("token") ?? "";
  if (
    !KEY_PATTERN.test(publicKey) ||
    !FILENAME_PATTERN.test(filename) ||
    !TOKEN_PATTERN.test(token)
  ) {
    return new NextResponse(null, { status: 404 });
  }

  const range = request.headers.get("range");
  let response: Response;
  try {
    response = await fetch(
      `${BACKEND_URL}/api/v1/embed/${encodeURIComponent(publicKey)}/generated/${encodeURIComponent(filename)}?token=${encodeURIComponent(token)}`,
      { headers: range ? { Range: range } : {}, cache: "no-store" },
    );
  } catch {
    return new NextResponse(null, { status: 502 });
  }

  if (response.status === 416) {
    return new NextResponse(null, {
      status: 416,
      headers: { "Content-Range": response.headers.get("content-range") ?? "" },
    });
  }
  if (response.status === 429) {
    // The link's own allowance, spent: said as itself, so a player backs off
    // rather than reading a broken gateway.
    const retryAfter = response.headers.get("retry-after");
    return new NextResponse(null, {
      status: 429,
      headers: retryAfter === null ? {} : { "Retry-After": retryAfter },
    });
  }
  if (!response.ok) {
    return new NextResponse(null, { status: response.status === 404 ? 404 : 502 });
  }
  const type = response.headers.get("content-type")?.split(";")[0]?.trim() ?? "";
  if (!MEDIA_TYPES.has(type)) {
    await response.body?.cancel();
    return new NextResponse(null, { status: 502 });
  }

  const passed = ["content-length", "content-range", "content-disposition"].flatMap((name) => {
    const value = response.headers.get(name);
    return value === null ? [] : [[name, value] as [string, string]];
  });
  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      ...Object.fromEntries(passed),
      "Accept-Ranges": "bytes",
      "Content-Type": type,
      // The address carries a link that lapses, and it is this visitor's: a shared
      // cache has no business holding it.
      "Cache-Control": "private, max-age=3600",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "sandbox",
    },
  });
}
