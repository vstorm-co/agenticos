"use client";

import { AudioLines } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Figure } from "@/components/ui";
import { useVoiceUsage } from "@/hooks/use-voice-usage";
import { periodEnd, periodStart } from "@/lib/dashboard/period";
import { runsHref } from "@/lib/runs/filter-params";
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
        <WidgetSkeleton variant="chart" />
      ) : error || usage === null ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : usage.calls === 0 ? (
        <WidgetEmptyBody
          icon={AudioLines}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <div className="flex h-full flex-col gap-4">
          <Figure
            value={t("minutes", { minutes: Math.round(usage.seconds / 60) })}
            caption={t("calls", { count: usage.calls })}
          />
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
                        className="hover:bg-muted/60 focus-visible:ring-ring flex items-center gap-3 rounded-lg px-1 py-2 outline-none focus-visible:ring-2"
                      >
                        <span
                          className="bg-foreground/[0.04] text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
                          aria-hidden
                        >
                          <AudioLines className="size-4" />
                        </span>
                        <span className="text-foreground min-w-0 flex-1 truncate font-medium">
                          {agent.agent_name}
                        </span>
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
