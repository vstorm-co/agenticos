"use client";

import { useSearchParams } from "next/navigation";

import { InvitationAcceptCard } from "@/components/orgs/invitation-accept-card";
import { INVITATION_FLOW_PARAM } from "@/lib/invitation-links";
import { acceptStagedInvitation } from "@/lib/invitation-staging";

/**
 * Closing a staged invitation once the invitee has signed in (#1414).
 *
 * An invitee who followed the deep link signed out had the token exchanged for an
 * httpOnly-cookie handle before login and was sent here afterwards; there is no
 * token in the URL to hold, only the `flow` naming which staging's cookie to redeem,
 * so the accept redeems that cookie server-side. The page is inside the dashboard,
 * so `AuthGuard` has already ensured a session - a handle that expired, or a page
 * opened without a flow or its cookie, is reported as a refused invitation by the
 * accept call, the same as any other.
 */
export function AcceptStagedInvitation() {
  const flow = useSearchParams().get(INVITATION_FLOW_PARAM);
  return <InvitationAcceptCard accept={() => acceptStagedInvitation(flow)} />;
}
