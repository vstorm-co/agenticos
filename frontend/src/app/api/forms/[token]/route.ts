import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

// `secrets.token_urlsafe` minted the link, so anything outside its alphabet is
// not one this deployment issued - refused before it reaches the network, since
// this route checks no cookie by design.
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * A visitor's answers to a workflow's public form, passed to the API.
 *
 * Proxied rather than posted at the API straight from the page for the logo
 * route's reason: the page is served from this origin, and the API may be on
 * another host or on plain `http`. The answer is passed back as the API gave it -
 * the thanks, the fields that are wrong, or the form being gone or busy.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  if (!TOKEN_PATTERN.test(token)) {
    return new NextResponse(null, { status: 404 });
  }
  try {
    const response = await fetch(
      `${BACKEND_URL}/api/v1/public/workflow-forms/${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: await request.text(),
        cache: "no-store",
      },
    );
    return new NextResponse(await response.text(), {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    return new NextResponse(null, { status: 502 });
  }
}
