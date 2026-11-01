"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";

/** The organization page's AI assistance switch, as a hash and a `data-tour` anchor. */
export const AI_ASSISTANCE_ANCHOR = "org-ai-assistance";

/** The grading model's setting, in the same section as the switch. */
export const GRADING_MODEL_ANCHOR = "org-grading-model";

/** Where the switch is - or another anchor in its section: the Governance tab, scrolled to it. */
export function aiAssistanceHref(orgId: string, anchor: string = AI_ASSISTANCE_ANCHOR): string {
  return `${ROUTES.ORG_MEMBERS(orgId)}?tab=governance#${anchor}`;
}

/**
 * A link to an organization's AI assistance switch that lands on it: the switch
 * sits below the fold of the organization page, so the link scrolls to it and
 * rings it, the way the Architect points at a control.
 */
export function EnableAiAssistanceLink({
  orgId,
  anchor = AI_ASSISTANCE_ANCHOR,
  children,
}: {
  orgId: string;
  /** Another setting of the section to land on, the grading model's say. */
  anchor?: string;
  children: ReactNode;
}) {
  const href = aiAssistanceHref(orgId, anchor);
  return (
    <Link href={href} onClick={() => void pointAt(anchor, href)} className="font-medium underline">
      {children}
    </Link>
  );
}
