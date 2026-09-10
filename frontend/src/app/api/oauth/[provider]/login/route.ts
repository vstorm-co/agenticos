import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/constants";

/**
 * Start an OAuth sign-in, attaching a staged invitation the browser cannot read.
 *
 * The provider login is a cross-origin navigation to the backend, so the httpOnly
 * `invitation_stage` cookie (#1414) cannot ride it directly. This same-origin hop
 * reads the cookie and forwards the opaque handle - never the token - as a query the
 * backend peeks for admission on an `invite_only` deployment. A sign-in with no
 * staged invitation carries none, and the handle is peeked, so it still closes the
 * acceptance after the round trip.
 */
const PROVIDERS = new Set(["google", "github", "microsoft"]);

interface RouteParams {
  params: Promise<{ provider: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  const { provider } = await params;
  // A path segment builds the redirect target, so it is checked against the known
  // providers rather than trusted - otherwise it is an open redirect - and encoded
  // even after that, the rule every hand-rolled proxy here keeps.
  if (!PROVIDERS.has(provider)) return new NextResponse(null, { status: 404 });

  const target = new URL(`${BACKEND_URL}/api/v1/oauth/${encodeURIComponent(provider)}/login`);
  const handle = request.cookies.get("invitation_stage")?.value;
  if (handle) target.searchParams.set("invitation_handle", handle);
  const response = NextResponse.redirect(target, 302);
  // The `Location` carries the handle, and a hand-rolled route owes the header the
  // proxy would otherwise stamp: this redirect is per-request and must not be cached.
  response.headers.set("Cache-Control", "no-store");
  return response;
}
