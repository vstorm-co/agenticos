"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";

/** The organization page's AI assistance switch, as a hash and a `data-tour` anchor. */
export const AI_ASSISTANCE_ANCHOR = "org-ai-assistance";

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
      href={`${ROUTES.ORG_MEMBERS(orgId)}#${AI_ASSISTANCE_ANCHOR}`}
      onClick={() => void pointAt(AI_ASSISTANCE_ANCHOR)}
      className="font-medium underline"
    >
      {children}
    </Link>
  );
}
