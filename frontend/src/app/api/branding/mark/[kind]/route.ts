import { NextRequest } from "next/server";

import { proxyBrandingImage } from "@/lib/branding-bytes";

/**
 * The deployment's logo or favicon, from bytes the API holds.
 *
 * One dynamic route rather than two static ones, under `mark/` rather than
 * directly under `branding/`: a `[kind]` sibling of the static `notice/` would
 * resolve correctly by Next's precedence rules and read like a trap, and
 * `platform-proxy.test.ts` - which sweeps every `/api/...` the client builds and
 * asks whether a route answers it - cannot resolve two static folders against one
 * interpolated path.
 *
 * A kind the whitelist does not name is a 404 rather than a forwarded request: the
 * segment reaches an API path, and the two images this deployment has are the two
 * it has.
 */
const KINDS = { logo: "logo", favicon: "favicon" } as const;

export async function GET(request: NextRequest, { params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  const known = KINDS[kind as keyof typeof KINDS];
  if (!known) return new Response(null, { status: 404 });
  return proxyBrandingImage(known, request.nextUrl.search);
}
