"use client";

import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";

import { useAgents, useOrganizationList, useSpend } from "@/hooks";
import { useOrgStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import { MARK_CLASS, QUIET_SURFACE } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { formatUsd } from "../format";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * How close the month is to its caps - the cause the outcomes donut only
 * shows the symptom of. Both figures are calendar-month by design (a cap is
 * monthly), so this card deliberately ignores the period filter. Per-agent
 * bars appear for agents whose published spec carries its own cap.
 *
 * Its "see all" is computed rather than taken from the registry, because the
 * page worth reaching from here is the one holding the cap, and that path
 * carries the organization's id. Raising the cap is still somewhere else -
 * this is navigation, not a budget-request flow.
 */
export function BudgetHeadroomWidget({ title, hint }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.budget-headroom");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const organizations = useOrganizationList();
  const { spend, isLoading, error, refetch } = useSpend();
  const { agents } = useAgents();

  const organization =
    organizations.data?.find((candidate) => candidate.id === activeOrgId) ??
    organizations.data?.[0];
  const cap =
    organization?.monthly_budget_usd != null ? Number(organization.monthly_budget_usd) : null;
  const used = Number(spend?.month_to_date_usd ?? 0);

  const perAgentUsed = new Map<string, number>();
  for (const row of spend?.by_agent ?? []) {
    perAgentUsed.set(row.agent_id, (perAgentUsed.get(row.agent_id) ?? 0) + Number(row.cost_usd));
  }
  const capped = agents.filter(
    (agent) => agent.budget_monthly_usd !== null && agent.budget_monthly_usd !== undefined,
  );

  return (
    <WidgetFrame
      title={title}
      hint={hint}
      seeAll={organization ? ROUTES.ORG_SETTINGS(organization.id) : undefined}
    >
      {isLoading || organizations.isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : cap === null ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-3">
          <div>
            <Figure
              value={`${Math.round((used / cap) * 100)}%`}
              caption={t("headline", {
                cap: formatUsd(cap),
                left: formatUsd(Math.max(cap - used, 0)),
              })}
            />
            <HeadroomBar used={used} cap={cap} className="mt-3" />
          </div>
          {capped.length > 0 ? (
            <div className="space-y-2">
              {capped.map((agent) => {
                const agentCap = agent.budget_monthly_usd ?? 0;
                const agentUsed = perAgentUsed.get(agent.id) ?? 0;
                return (
                  <div key={agent.id} className="text-xs">
                    <div className="flex justify-between gap-2">
                      <span className="text-muted-foreground truncate">{agent.name}</span>
                      <span className="text-foreground shrink-0 tabular-nums">
                        {formatUsd(agentUsed)} / {formatUsd(agentCap)}
                      </span>
                    </div>
                    <HeadroomBar used={agentUsed} cap={agentCap} className="mt-1" />
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      )}
    </WidgetFrame>
  );
}

/**
 * A meter, not a bar in a list: its fill changes hue as the month fills up, so
 * the track stays the neutral quiet surface. A track in the fill's own hue is
 * the rule where the fill has one hue - it would fight a red fill here.
 */
function HeadroomBar({ used, cap, className }: { used: number; cap: number; className?: string }) {
  const share = cap > 0 ? Math.min(used / cap, 1) : 0;
  return (
    <div className={cn("h-2 overflow-hidden rounded-r-sm", QUIET_SURFACE, className)}>
      <div
        className={cn(
          "h-full rounded-r-sm",
          share >= 0.9 ? "bg-destructive" : share >= 0.7 ? "bg-warning" : MARK_CLASS,
        )}
        style={{ width: `${share * 100}%` }}
      />
    </div>
  );
}
