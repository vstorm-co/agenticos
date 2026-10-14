"use client";

import { AudioLines } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";
import { useVoiceUsage } from "@/hooks/use-voice-usage";
import { periodEnd, periodStart } from "@/lib/dashboard/period";
import { MARK_CLASS, QUIET_SURFACE } from "@/lib/dashboard/system";
import { runsHref } from "@/lib/runs/filter-params";
import { cn } from "@/lib/utils";
import type { VoiceUsage } from "@/types/voice";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many agents the card names; Activity has the rest. */
const SHOWN = 3;

/**
 * Call minutes (#54): the period's minutes and calls, which agents took them,
 * and this calendar month's minutes against the organization's monthly limit -
 * the figure a call is refused at. The period is the page's own inclusive
 * window, sent as its first and last instant like every other usage card.
 * "See all" opens Activity on the same window, narrowed to calls.
 */
export function VoiceMinutesWidget({ title, hint, period, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.voice-minutes");
  const { usage, isLoading, error, refetch } = useVoiceUsage(
    { start: periodStart(period), end: periodEnd(period) },
    { enabled: true },
  );
  const calls = (agentId?: string) => runsHref({ period, agentId, filters: { modality: "voice" } });

  return (
    <WidgetFrame title={title} hint={hint} seeAll={calls()} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error || usage === null ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : usage.calls === 0 && usage.month_seconds === 0 ? (
        <WidgetEmptyBody
          icon={AudioLines}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex h-full flex-col justify-between gap-3">
          <Figure
            value={t("minutes", { minutes: Math.round(usage.seconds / 60) })}
            caption={t("calls", { count: usage.calls })}
          />
          <MonthMeter usage={usage} />
          {usage.by_agent.length > 0 ? (
            <ul className="space-y-1 text-xs">
              {usage.by_agent.slice(0, SHOWN).map((agent) => {
                const minutes = (
                  <span className="text-foreground shrink-0 tabular-nums">
                    {t("minutes", { minutes: Math.round(agent.seconds / 60) })}
                  </span>
                );
                return (
                  <li key={agent.agent_id ?? "deleted"}>
                    {agent.agent_id === null ? (
                      // A deleted agent's calls have no runs page to open.
                      <span className="flex justify-between gap-2">
                        <span className="text-muted-foreground truncate italic">
                          {t("deletedAgent")}
                        </span>
                        {minutes}
                      </span>
                    ) : (
                      <Link
                        href={calls(agent.agent_id)}
                        className="hover:bg-accent/40 flex justify-between gap-2 rounded-sm"
                      >
                        <span className="text-muted-foreground truncate">{agent.agent_name}</span>
                        {minutes}
                      </Link>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      )}
    </WidgetFrame>
  );
}

/** This month against the limit, or the month alone when only budgets bound calls. */
function MonthMeter({ usage }: { usage: VoiceUsage }) {
  const t = useTranslations("dashboard.widgets.voice-minutes");
  const used = Math.round(usage.month_seconds / 60);
  const limit = usage.monthly_minutes;
  if (limit === null) {
    return <p className="text-muted-foreground text-xs">{t("noLimit", { used })}</p>;
  }
  const share = Math.min(used / limit, 1);
  return (
    <div className="text-xs">
      <p className="text-muted-foreground">{t("monthUsed", { used, limit })}</p>
      <div
        role="meter"
        aria-label={t("month")}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
        className={cn("mt-1 h-2 overflow-hidden rounded-r-sm", QUIET_SURFACE)}
      >
        <div
          className={cn(
            "h-full rounded-r-sm",
            share >= 0.9 ? "bg-destructive" : share >= 0.7 ? "bg-warning" : MARK_CLASS,
          )}
          style={{ width: `${share * 100}%` }}
        />
      </div>
    </div>
  );
}
