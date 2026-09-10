/**
 * Reading the token out of an invitation deep link, and carrying its landing
 * through the sign-up detour.
 *
 * An invitee with no account opens `/invitations/<token>`, which sits inside the
 * dashboard, so `AuthGuard` catches them signed out. Before it sends them to sign
 * in it exchanges the token for an `httpOnly`-cookie handle (#1414), so what rides
 * the round trip is a credential-free `returnTo` (`/invitations/pending`) rather than
 * the token. `invitationTokenFrom` is what reads the token off the path for that
 * exchange; `registerHref` carries the landing on to the sign-up form, so an invitee
 * who needs an account still returns to close the invitation afterwards.
 */

import { ROUTES } from "@/lib/constants";

/** Matches `/invitations/<token>`, with or without a locale prefix. */
const INVITATION_PATH = /^\/(?:[a-z]{2}\/)?invitations\/([A-Za-z0-9_-]+)\/?$/;

/**
 * The invitation token a path is pointing at, if it is a `/invitations/<token>` one.
 *
 * Deliberately strict about the shape: a token is the only path segment this reads,
 * and anything else - a query, a second segment, the credential-free
 * `/invitations/pending` landing - yields nothing rather than a guess. `AuthGuard`
 * reads the token off the current path with it; a sanitizer keeps the same shape out
 * of session storage.
 */
export function invitationTokenFrom(returnTo: string | null | undefined): string | null {
  if (!returnTo) return null;
  const token = INVITATION_PATH.exec(returnTo)?.[1] ?? null;
  // `/invitations/pending` matches the shape but is the credential-free landing, not
  // a token - a real token is a long random string, never the literal `pending`. So
  // a signed-out load of the landing does not stage `pending`, and the sanitizer does
  // not rewrite it to itself.
  return token === "pending" ? null : token;
}

/**
 * Where "create an account" should point, given the query the login page was given.
 *
 * The `returnTo` is carried through unchanged - it is the credential-free
 * `/invitations/pending` landing now, not the token - because registering does not
 * accept the invitation: that is a separate call needing a session, so the person
 * still has to land back on the pending page afterwards.
 */
export function registerHref(search: string): string {
  const returnTo = new URLSearchParams(search).get("returnTo");
  if (!returnTo) return ROUTES.REGISTER;
  return `${ROUTES.REGISTER}?${new URLSearchParams({ returnTo }).toString()}`;
}
