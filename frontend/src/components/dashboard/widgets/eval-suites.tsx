"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";
import { useTranslations } from "next-intl";

import { RESULT_TONE, suiteState, type SuiteState } from "@/components/evals/suites/suite-format";
import { Badge } from "@/components/ui";
import { useVisibleEvalSuites } from "@/hooks/use-eval-suites";
import { ROUTES } from "@/lib/constants";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many a card lists; each agent's Evals tab has the rest. */
const SHOWN = 6;

/** The order a reader scans them in: what needs looking at first. */
const ORDER: SuiteState[] = ["failing", "waiting", "passing", "paused"];

/**
 * The organization's eval suites at a glance: how many pass, fail, wait for
 * their first run or are paused, and the ones needing a look first - each one
 * click from its agent's Evals tab. Counted, not charted: a handful of suites
 * is a handful of numbers.
 */
export function EvalSuitesWidget({ title, hint, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.eval-suites");
  const tSuites = useTranslations("evals.suites");
  const { suites, isLoading, error, refetch } = useVisibleEvalSuites();
  const counts = ORDER.map((state) => ({
    state,
    count: suites.filter((suite) => suiteState(suite) === state).length,
  })).filter(({ count }) => count > 0);
  const shown = [...suites]
    .sort((a, b) => ORDER.indexOf(suiteState(a)) - ORDER.indexOf(suiteState(b)))
    .slice(0, SHOWN);

  return (
    <WidgetFrame title={title} hint={hint} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : suites.length === 0 ? (
        <WidgetEmptyBody icon={ListChecks} title={t("empty")} />
      ) : (
        <div className="space-y-2">
          <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
            {counts.map(({ state, count }) => (
              <span key={state}>{t(`count.${state}`, { count })}</span>
            ))}
          </p>
          <ul className="divide-border divide-y">
            {shown.map((suite) => (
              <li key={suite.id}>
                <Link
                  href={`${ROUTES.AGENTS}/${suite.agent_id}?tab=evals`}
                  className="hover:bg-accent/40 flex items-center justify-between gap-3 rounded-md px-2 py-2.5"
                >
                  <span className="min-w-0 truncate text-sm">
                    {t("row", { suite: suite.name, agent: suite.agent_name })}
                  </span>
                  {suite.last_result ? (
                    <Badge variant={RESULT_TONE[suite.last_result.status]}>
                      {tSuites(`status.${suite.last_result.status}`)}
                    </Badge>
                  ) : (
                    <Badge variant="outline">{t("never")}</Badge>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </WidgetFrame>
  );
}
