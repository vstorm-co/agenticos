import { NextRequest, NextResponse } from "next/server";
import { INVITATION_FLOW_PARAM, isInvitationFlow, stageCookieName } from "@/lib/invitation-links";
import { readPublicConfig } from "@/lib/public-config";

/**
 * Start an OAuth sign-in, attaching a staged invitation the browser cannot read.
 *
 * The provider login is a cross-origin navigation to the backend, so the httpOnly
 * staging cookie (#1414) cannot ride it directly. This same-origin hop reads the
 * cookie of the flow the button named in `?flow=` and forwards the opaque handle -
 * never the token - as a query the backend peeks for admission on an `invite_only`
 * deployment. A sign-in with no staged invitation carries none, and the handle is
 * peeked, so it still closes the acceptance after the round trip.
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

  // The browser follows this redirect, so it is the public API origin the
  // deployment names at runtime, read per request like every other public URL (#1544).
  const { apiUrl } = readPublicConfig(process.env);
  const target = new URL(`${apiUrl}/api/v1/oauth/${encodeURIComponent(provider)}/login`);
  const flow = request.nextUrl.searchParams.get(INVITATION_FLOW_PARAM);
  const handle = isInvitationFlow(flow) ? request.cookies.get(stageCookieName(flow))?.value : null;
  if (handle) target.searchParams.set("invitation_handle", handle);
  const response = NextResponse.redirect(target, 302);
  // The `Location` carries the handle, and a hand-rolled route owes the header the
  // proxy would otherwise stamp: this redirect is per-request and must not be cached.
  response.headers.set("Cache-Control", "no-store");
  return response;
}
