"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useAgentAttention } from "@/hooks/use-usage-stats";
import { ROUTES } from "@/lib/constants";
import { resolvePreset } from "@/lib/dashboard/period";

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

/** Whether the agent had answers rated down or runs that failed in the last thirty days. */
export function useNeedsImprovement(agentId: string, { enabled }: { enabled: boolean }) {
  const lately = resolvePreset("30d");
  const { agents } = useAgentAttention({ from: lately.from, to: lately.to }, { enabled });
  const item = agents.find((agent) => agent.agent_id === agentId);
  return item !== undefined && (item.rated_down > 0 || item.failed_runs > 0);
}
