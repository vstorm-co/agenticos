"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";

/** The organization page's AI assistance switch, as a hash and a `data-tour` anchor. */
export const AI_ASSISTANCE_ANCHOR = "org-ai-assistance";

/** Where the switch is: the organization page's Governance tab, scrolled to it. */
export function aiAssistanceHref(orgId: string): string {
  return `${ROUTES.ORG_MEMBERS(orgId)}?tab=governance#${AI_ASSISTANCE_ANCHOR}`;
}

/**
 * A link to an organization's AI assistance switch that lands on it: the switch
 * sits below the fold of the organization page, so the link scrolls to it and
 * rings it, the way the Architect points at a control.
 */
export function EnableAiAssistanceLink({
  orgId,
  children,
}: {
  orgId: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={aiAssistanceHref(orgId)}
      onClick={() => void pointAt(AI_ASSISTANCE_ANCHOR)}
      className="font-medium underline"
    >
      {children}
    </Link>
  );
}
