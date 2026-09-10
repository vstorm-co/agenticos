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

/**
 * Exchange an invitation token for the server-set handle cookie.
 *
 * Returns whether it named a live invitation: a forged or expired token is refused,
 * and the caller sends the invitee on to sign in either way - the pending page is
 * where an invalid one is finally reported, once there is a session to report it to.
 */
export async function stageInvitation(token: string): Promise<boolean> {
  try {
    await apiClient.post("/invitations/stage", { token });
    return true;
  } catch {
    return false;
  }
}

/** Redeem the staged handle and accept the invitation as the signed-in user. */
export async function acceptStagedInvitation(): Promise<void> {
  await apiClient.post("/invitations/pending/accept");
}
