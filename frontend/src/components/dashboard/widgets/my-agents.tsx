"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { useAgents, usePermissions, useUsageStats } from "@/hooks";
import { useAuthStore } from "@/stores";
import { agentTag, filterAgentRows, myAgentsPolicy } from "@/lib/dashboard/my-agents";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * The caller's agents - and only as much as their permissions say. Three
 * inner checks, all from the same injected policy: without agents:edit the
 * list narrows to what was shared, run counts render only under runs:view
 * (and only then is the usage query even issued), and the chat link only
 * under agents:run - a control the caller may not use is not rendered.
 */
export function MyAgentsWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.my-agents");
  const { can } = usePermissions();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const policy = myAgentsPolicy(can);
  const { agents, isLoading, error, refetch } = useAgents();
  const usage = useUsageStats(
    { from: period.from, to: period.to },
    { enabled: policy.showRunCounts },
  );
  const runCounts = new Map(
    (usage.usage?.by_agent ?? []).map((row) => [row.agent_id, row.runs]),
  );

  const rows = filterAgentRows(agents, policy, userId).slice(0, 6);

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : rows.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {rows.map((agent) => {
            const tag = agentTag(agent, userId);
            return (
              <li
                key={agent.id}
                className="border-border flex min-w-0 flex-col gap-1 rounded-lg border p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-foreground truncate text-sm font-medium">
                    {agent.name}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium",
                      tag === "yours" ? "bg-chart/10 text-chart" : "bg-muted text-muted-foreground",
                    )}
                  >
                    {t(tag)}
                  </span>
                </div>
                <div className="text-muted-foreground flex items-center justify-between gap-2 text-xs">
                  {policy.showRunCounts ? (
                    <span>{t("runs", { count: runCounts.get(agent.id) ?? 0 })}</span>
                  ) : (
                    <span />
                  )}
                  {policy.showOpenChat ? (
                    <Link href={ROUTES.CHAT} className="hover:text-foreground">
                      {t("openChat")}
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
