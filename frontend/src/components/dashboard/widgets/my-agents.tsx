"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, usePermissions, useUsageStats } from "@/hooks";
import { useAuthStore } from "@/stores";
import { agentTag, filterAgentRows, myAgentsPolicy } from "@/lib/dashboard/my-agents";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { ArrowUpRight, Bot } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The caller's agents - and only as much as their permissions say. Three
 * inner checks, all from the same injected policy: without agents:edit the
 * list narrows to what was shared, run counts render only under runs:view
 * (and only then is the usage query even issued), and the chat link only
 * under agents:run - a control the caller may not use is not rendered.
 */
export function MyAgentsWidget({ title, hint, period, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-agents");
  const { can } = usePermissions();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const policy = myAgentsPolicy(can);
  const { agents, isLoading, error, refetch } = useAgents();
  const usage = useUsageStats(
    { from: period.from, to: period.to },
    { enabled: policy.showRunCounts },
  );
  const runCounts = new Map((usage.usage?.by_agent ?? []).map((row) => [row.agent_id, row.runs]));

  const rows = filterAgentRows(agents, policy, userId).slice(0, 6);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody icon={Bot} title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
          {rows.map((agent) => {
            const tag = agentTag(agent, userId);
            return (
              <li key={agent.id} className="flex min-w-0 flex-col gap-2">
                <div className="flex items-center gap-2.5">
                  {/* The agent's own face, the same one the catalog, the run
                      table and the chat picker draw - a list of agents told
                      apart by six lines of text is a list nobody scans. */}
                  <AgentAvatar
                    agentId={agent.id}
                    slug={agent.slug}
                    hasAvatar={agent.has_avatar ?? false}
                    size="md"
                    colorSlot={agent.avatar_color}
                  />
                  {/* The name reaches the agent. Every other card on this page
                      hands over to the page behind its number; this one named
                      six agents and offered no way to open any of them. */}
                  <Link
                    href={ROUTES.AGENT_DETAIL(agent.id)}
                    className="text-foreground min-w-0 flex-1 truncate text-sm font-medium hover:underline"
                  >
                    {agent.name}
                  </Link>
                  <span className="text-muted-foreground shrink-0 text-xs">{t(tag)}</span>
                </div>
                <div className="text-muted-foreground flex items-center justify-between gap-2 text-xs">
                  {policy.showRunCounts ? (
                    <span>{t("runs", { count: runCounts.get(agent.id) ?? 0 })}</span>
                  ) : (
                    <span />
                  )}
                  {policy.showOpenChat ? (
                    <Link
                      href={ROUTES.CHAT}
                      className="hover:text-foreground inline-flex items-center gap-1"
                    >
                      {t("openChat")}
                      <ArrowUpRight className="h-3 w-3" aria-hidden />
                    </Link>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </WidgetFrame>
  );
}
