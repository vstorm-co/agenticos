"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { EXTERNAL_LINK_PROPS, type LegalLink } from "@/lib/legal-links";

/**
 * A link to whichever terms or policy this deployment actually uses.
 *
 * One component because the destination decides the element: a built-in page is a
 * `next/link` navigation, and an operator's own policy is on another origin and
 * opens in a new tab. A half-filled sign-up form is the reason - sending somebody
 * off-site in the same tab to read a policy loses what they had typed.
 */
export function LegalAnchor({ link, children }: { link: LegalLink; children: ReactNode }) {
  const className = "text-foreground/70 hover:text-foreground underline-offset-4 hover:underline";

  if (link.external) {
    return (
      <a href={link.href} className={className} {...EXTERNAL_LINK_PROPS}>
        {children}
      </a>
    );
  }
  return (
    <Link href={link.href} className={className}>
      {children}
    </Link>
  );
}
