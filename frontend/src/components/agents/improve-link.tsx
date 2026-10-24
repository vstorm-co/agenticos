"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { ROUTES } from "@/lib/constants";

/** Open the resumable improvement flow for this agent. */
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
    <Link href={`${ROUTES.AGENT_DETAIL(agentId)}/improve/new`} className={className}>
      {children}
    </Link>
  );
}
