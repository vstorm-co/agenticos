"use client";

import { InvitationAcceptCard } from "@/components/orgs/invitation-accept-card";
import { acceptStagedInvitation } from "@/lib/invitation-staging";

/**
 * Closing a staged invitation once the invitee has signed in (#1414).
 *
 * An invitee who followed the deep link signed out had the token exchanged for an
 * httpOnly-cookie handle before login and was sent here afterwards; there is no
 * token in the URL to hold, so the accept redeems that cookie server-side. The
 * page is inside the dashboard, so `AuthGuard` has already ensured a session - a
 * handle that expired or a page opened without one is reported as a refused
 * invitation by the accept call, the same as any other.
 */
export function AcceptStagedInvitation() {
  return <InvitationAcceptCard accept={acceptStagedInvitation} />;
}
