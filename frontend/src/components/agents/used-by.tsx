"use client";

import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { AgentUsage } from "@/types/agents";

const NAMED = 2;

/**
 * Which agents use a skill, a context file or a knowledge base (#2075).
 *
 * "Not used by any agent yet" is the line worth reading: something written and
 * never given to an agent does nothing, and the card is where its author looks.
 * Nothing for a response that did not say, rather than a claim of "nowhere".
 */
export function UsedBy({ agents, className }: { agents?: AgentUsage[]; className?: string }) {
  const t = useTranslations("agents");
  if (agents === undefined) return null;
  const names = agents
    .slice(0, NAMED)
    .map((agent) => agent.name)
    .join(", ");
  return (
    <span
      className={cn("text-muted-foreground flex min-w-0 items-center gap-1 text-xs", className)}
      title={agents.map((agent) => agent.name).join(", ") || undefined}
    >
      <Bot className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">
        {agents.length === 0
          ? t("usedByNobody")
          : t("usedBy", { names, more: Math.max(0, agents.length - NAMED) })}
      </span>
    </span>
  );
}
