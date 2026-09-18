"use client";

import { useInvitations, useAuth } from "@/hooks";
import { InvitationAcceptCard } from "@/components/orgs/invitation-accept-card";

/**
 * Accepting an invitation directly, for a signed-in holder of the link.
 *
 * Separate from the page so it can be tested: the page's only job is to unwrap
 * `params`, and `use()` on a promise does not settle under the test renderer - so
 * anything asserted through the page passes whether or not the page works.
 *
 * **It navigates nowhere when nobody is signed in.** `AuthGuard`, which wraps every
 * dashboard route, has already sent that visitor to `/login?returnTo=…` - and for
 * an invitation deep link it exchanges the token for an httpOnly handle first
 * (#1414), so the signed-out path returns here only for someone who was already
 * signed in. This used to push `?redirect=` of its own - a name nothing reads - and
 * because it renders only once the guard has decided, that push replaced the
 * guard's. An invitee with no account then reached a bare `/register` and arrived,
 * signed up, in no organization at all (#1495).
 */
export function AcceptInvitation({ token }: { token: string }) {
  const { isAuthenticated } = useAuth();
  const { acceptInvitation } = useInvitations("");

  if (!isAuthenticated) return null;

  return <InvitationAcceptCard accept={() => acceptInvitation(token)} />;
}
