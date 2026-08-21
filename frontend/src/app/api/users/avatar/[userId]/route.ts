import { NextRequest, NextResponse } from "next/server";

import { IMAGE_TYPES, baseContentType } from "@/lib/proxy-content-type";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// The backend signature is `user_id: UUID`, so anything else is a bad request
// here rather than a round trip. This route takes a client-controlled path
// segment and has no cookie check - deliberately, because avatars are served
// publicly - which made it the one place an anonymous caller could reach the
// internal backend. Interpolated raw, `%2F` decodes into the param and `fetch`
// then normalises `..`, so `x%2F..%2F..%2F..%2Fopenapi.json` arrived at the
// backend as `GET /api/v1/openapi.json`. Encoding alone closes it; validating
// the shape means a malformed segment never reaches the network at all.
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ userId: string }> },
) {
  try {
    const { userId } = await params;

    if (!UUID_PATTERN.test(userId)) {
      return new NextResponse(null, { status: 400 });
    }

    const response = await fetch(
      `${BACKEND_URL}/api/v1/users/avatar/${encodeURIComponent(userId)}`,
    );

    if (!response.ok) {
      return new NextResponse(null, { status: response.status });
    }

    // Pinned to an image type rather than echoed. This response is served from
    // the app's own origin, whose CSP allows inline script, and the file behind
    // it was accepted on a declared Content-Type, never its bytes (#702). An
    // unnamed type is refused too: a default of image/jpeg over unknown bytes is
    // a guess this route has no reason to make.
    const contentType = baseContentType(response.headers.get("content-type"));
    if (!IMAGE_TYPES.has(contentType)) {
      return new NextResponse(null, { status: 502 });
    }
    const imageBuffer = await response.arrayBuffer();

    return new NextResponse(imageBuffer, {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return new NextResponse(null, { status: 500 });
  }
}
