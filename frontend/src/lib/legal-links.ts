/**
 * Where "Terms" and "Privacy" point, once a deployment has its own.
 *
 * The built-in `/legal/*` pages describe *our* terms, which is exactly wrong for
 * a deployment running under somebody else's name - so an administrator can point
 * these outward instead. Set, and every link that offered our page offers theirs.
 *
 * The `external` flag is not cosmetic. An in-app route is a `next/link`
 * navigation; a client's own policy is on another origin, and opening it in the
 * same tab from a half-filled sign-up form loses what the visitor had typed.
 */

import type { Branding } from "@/lib/branding";
import { ROUTES } from "@/lib/constants";

export interface LegalLink {
  href: string;
  /** True when the destination is the operator's own site rather than a page here. */
  external: boolean;
}

export function termsLink(branding: Pick<Branding, "termsUrl">): LegalLink {
  return branding.termsUrl
    ? { href: branding.termsUrl, external: true }
    : { href: ROUTES.LEGAL_TERMS, external: false };
}

export function privacyLink(branding: Pick<Branding, "privacyUrl">): LegalLink {
  return branding.privacyUrl
    ? { href: branding.privacyUrl, external: true }
    : { href: ROUTES.LEGAL_PRIVACY, external: false };
}

/** What an external link needs so a new tab cannot reach back into this one. */
export const EXTERNAL_LINK_PROPS = { target: "_blank", rel: "noopener noreferrer" } as const;
