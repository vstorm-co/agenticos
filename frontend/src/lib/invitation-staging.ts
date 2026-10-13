/**
 * The client half of the invitation server-side exchange (#1414).
 *
 * An invitee follows `/invitations/<token>` while signed out. Rather than carry the
 * token through the sign-in round trip - in a `returnTo` query, in browser history,
 * in `sessionStorage` - it is handed to the server here, before the redirect to
 * login. The server stores it under an opaque handle and sets that handle as an
 * `httpOnly` cookie no script can read; all that comes back is whether the token
 * named a live invitation. After sign-in the same cookie closes the acceptance.
 */

import { apiClient } from "@/lib/api-client";
import { INVITATION_FLOW_PARAM } from "@/lib/invitation-links";

/**
 * Exchange an invitation token for the server-set handle cookie.
 *
 * Answers the flow id the exchange minted - what the pending landing carries so the
 * accept can find this staging's cookie among any others - or `null` when the token
 * was not staged. A forged or expired token is refused, but so is a transient
 * failure or a rate limit, and the caller cannot tell them apart from here; it keeps
 * the invitee on the link they hold and offers to try again, rather than sending
 * them to sign in with nothing staged to come back to.
 */
export async function stageInvitation(token: string): Promise<string | null> {
  try {
    const { flow } = await apiClient.post<{ staged: boolean; flow: string }>("/invitations/stage", {
      token,
    });
    return flow;
  } catch {
    return null;
  }
}

/**
 * Redeem the flow's staged handle and accept the invitation as the signed-in user.
 *
 * A landing reached with no flow still asks, and is refused as a miss: there is no
 * cookie to redeem, and the card reports it the same way it reports a lapsed one.
 */
export async function acceptStagedInvitation(flow: string | null): Promise<void> {
  const path = flow
    ? `/invitations/pending/accept?${INVITATION_FLOW_PARAM}=${encodeURIComponent(flow)}`
    : "/invitations/pending/accept";
  await apiClient.post(path);
}
