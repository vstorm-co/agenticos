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
 *
 * The landing names a **flow**: a random id the exchange mints, carried as
 * `?flow=<id>` on the pending URL and in the name of the cookie holding the handle.
 * One fixed cookie name meant two invitation links opened side by side while signed
 * out overwrote each other, and both pending tabs then redeemed the second - the
 * flow id binds each tab to the handle staged for it. The id is not a credential:
 * without the `httpOnly` cookie it names nothing, which is why it may ride the URL
 * and `sessionStorage` where the token never could.
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

/** The query parameter the pending landing carries its flow id under. */
export const INVITATION_FLOW_PARAM = "flow";

/** A flow id is 32 lower-case hex digits - a UUID with the dashes dropped. */
const FLOW_ID = /^[0-9a-f]{32}$/;

/** Matches the pending landing's path, with or without a locale prefix. */
const PENDING_PATH = /^\/(?:[a-z]{2}\/)?invitations\/pending\/?$/;

/** Whether a value has the shape of a flow id; a cookie name is built from it. */
export function isInvitationFlow(value: string | null | undefined): value is string {
  return typeof value === "string" && FLOW_ID.test(value);
}

/** The `httpOnly` cookie holding one flow's staged handle. */
export function stageCookieName(flow: string): string {
  return `invitation_stage_${flow}`;
}

/** The credential-free landing that redeems one flow after sign-in. */
export function pendingLandingFor(flow: string): string {
  return `${ROUTES.INVITATION_PENDING}?${INVITATION_FLOW_PARAM}=${flow}`;
}

/**
 * The flow id a `returnTo` is bound to, if it is the pending landing for one.
 *
 * Reads only the shape {@link pendingLandingFor} produces - a same-origin path to
 * the landing with a well-formed `flow` - and answers nothing for anything else, an
 * absolute URL included. The register form reads the invited signal off it and hands
 * the id on to the register proxy; the provider buttons hand it to the OAuth start.
 */
export function invitationFlowFrom(returnTo: string | null | undefined): string | null {
  if (!returnTo || !returnTo.startsWith("/") || returnTo.startsWith("//")) return null;
  const url = new URL(returnTo, "http://placeholder.invalid");
  if (!PENDING_PATH.test(url.pathname)) return null;
  const flow = url.searchParams.get(INVITATION_FLOW_PARAM);
  return isInvitationFlow(flow) ? flow : null;
}
