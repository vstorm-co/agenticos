"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";

/** The assistant's card on an agent's Build tab, where improving it starts. */
const ASSISTANT = "agent-assistant-strip";

/**
 * Where an agent is improved: its Build tab, scrolled to the assistant's card
 * and ringed - the way the Architect points at a control.
 */
export function ImproveLink({
  agentId,
  className,
  children,
}: {
  agentId: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={`${ROUTES.AGENT_DETAIL(agentId)}?tab=build`}
      onClick={() => void pointAt(ASSISTANT)}
      className={className}
    >
      {children}
    </Link>
  );
}
