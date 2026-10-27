"use client";

import Link from "next/link";
import { CircleCheck, TrendingUp } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImprovementsAwaiting } from "@/hooks/use-improvements";
import { ROUTES } from "@/lib/constants";
import { stopOf } from "@/lib/improvement-steps";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; the newest come first. */
const SHOWN = 5;

/**
 * Improvement sessions waiting for a person: stopped after a step, or with a
 * result to review. Each opens its session at the step that waits.
 */
export function ImprovementsWaitingWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.improvements-waiting");
  const { sessions, isLoading, error, refetch } = useImprovementsAwaiting();
  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : sessions.length === 0 ? (
        <WidgetEmptyBody
          icon={CircleCheck}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="divide-border divide-y text-sm">
          {sessions.slice(0, SHOWN).map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 space-y-0.5">
                <Link
                  href={ROUTES.AGENT_DETAIL(item.agent_id)}
                  className="block truncate font-medium"
                >
                  {item.agent_name}
                </Link>
                <span className="text-muted-foreground block truncate text-xs">
                  {t(item.next_step_blocked ? "what.blocked" : `what.${stopOf(item) ?? "result"}`)}
                </span>
              </span>
              <Button asChild size="sm" variant="outline" className="shrink-0">
                <Link href={`${ROUTES.AGENT_DETAIL(item.agent_id)}/improve/${item.id}`}>
                  <TrendingUp className="h-4 w-4" aria-hidden />
                  {t("open")}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
