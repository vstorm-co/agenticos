/**
 * Carrying an invitation from the link somebody was sent to the form they need.
 *
 * The problem this solves is a chain of redirects that loses the token. An invitee
 * with no account opens `/invitations/<token>`, which sits inside the dashboard, so
 * `AuthGuard` bounces them to `/login?returnTo=%2Finvitations%2F<token>`. From there
 * the only way to a sign-up form was a plain link to `/register` - and on a
 * deployment set to `invite_only` that form then refused them, holding a valid
 * invitation, because the request carried no token and no query over their address
 * can recognise a link constraining no address (#916).
 *
 * So the token is read back out of `returnTo` and put on the register link. Parsing a
 * URL this app itself produced, in one place with a test, rather than threading a
 * second parameter through a redirect nobody owns.
 */

import { ROUTES } from "@/lib/constants";

/** Matches `/invitations/<token>`, with or without a locale prefix. */
const INVITATION_PATH = /^\/(?:[a-z]{2}\/)?invitations\/([A-Za-z0-9_-]+)\/?$/;

/**
 * The invitation token a `returnTo` is pointing at, if it is pointing at one.
 *
 * Deliberately strict about the shape: a token is the only path segment this reads,
 * and anything else - a query, a second segment, an absolute URL to somewhere else -
 * yields nothing rather than a guess.
 */
export function invitationTokenFrom(returnTo: string | null | undefined): string | null {
  if (!returnTo) return null;
  return INVITATION_PATH.exec(returnTo)?.[1] ?? null;
}

/**
 * Where "create an account" should point, given the query the login page was given.
 *
 * The `returnTo` is kept as well as the token: registering does not accept the
 * invitation - that is a separate call needing a session - so the person still has to
 * land back on the invitation page afterwards.
 */
export function registerHref(search: string): string {
  const params = new URLSearchParams(search);
  const returnTo = params.get("returnTo");
  const token = invitationTokenFrom(returnTo);
  if (!token) return ROUTES.REGISTER;

  const next = new URLSearchParams({ invitation: token, returnTo: returnTo as string });
  return `${ROUTES.REGISTER}?${next.toString()}`;
}
