"use client";

import type { ReactNode } from "react";
import { Cpu } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states";
import { useAgent } from "@/hooks/use-agents";
import { ROUTES } from "@/lib/constants";
import { isSystemAgent } from "@/lib/system-agents";

/**
 * A page under an agent that only an ordinary agent has - an eval run, an
 * improvement session - and what it says in their place for a system agent.
 *
 * Nobody chats with a system agent, so it is never the agent an eval tests or an
 * improvement changes; the server refuses both. A link can still name one, and
 * the page says why there is nothing here rather than opening a wizard whose every
 * step is refused. Until the agent has loaded, the page renders as it would.
 */
export function OrdinaryAgentRoute({
  agentId,
  children,
}: {
  agentId: string;
  children: ReactNode;
}) {
  const t = useTranslations("agents");
  const { agent } = useAgent(agentId);
  if (!agent || !isSystemAgent(agent.kind)) return <>{children}</>;
  return (
    <EmptyState
      icon={Cpu}
      title={t("systemAgentRouteTitle", { name: agent.name })}
      description={t("systemAgentRouteBody")}
      cta={{ label: t("systemAgentRouteBack"), href: ROUTES.AGENT_DETAIL(agentId) }}
    />
  );
}
